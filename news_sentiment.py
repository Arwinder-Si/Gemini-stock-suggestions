import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

"""
News-Sentiment Feature Pipeline
=================================
Standalone daily batch job that fetches headlines for each stock in the
universe, runs sentiment analysis, tags events, and outputs a compact
feature table (news_features.csv) for the screener to consume.

Usage:
    python news_sentiment.py          # Run for all stocks
    python news_sentiment.py RITES    # Run for a single stock (debug)

Data source: yfinance .news API (free, no API key needed).
Sentiment: FinBERT (HuggingFace) if available, TextBlob fallback.
"""

import logging
import os
import re
import time
import warnings
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

warnings.filterwarnings('ignore')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# =============================================================================
# STOCK UNIVERSE (same as comprehensive_screener.py)
# =============================================================================
NIFTY_LARGE = [
    'RELIANCE', 'TCS', 'HDFCBANK', 'ICICIBANK', 'BHARTIARTL', 'SBIN', 'INFY',
    'ITC', 'HINDUNILVR', 'LT', 'BAJFINANCE', 'HCLTECH', 'MARUTI',
    'SUNPHARMA', 'ADANIENT', 'KOTAKBANK', 'TITAN', 'ONGC',
    'NTPC', 'AXISBANK', 'DMART', 'ADANIPORTS', 'ULTRACEMCO',
    'ASIANPAINT', 'COALINDIA', 'BAJAJFINSV', 'BAJAJ-AUTO', 'POWERGRID',
    'NESTLEIND', 'WIPRO', 'M&M', 'IOC', 'HAL', 'DLF',
    'JSWSTEEL', 'TATASTEEL', 'SIEMENS', 'IRFC', 'PIDILITIND',
    'GRASIM', 'SBILIFE', 'BEL', 'TRENT', 'PNB', 'INDIGO', 'BANKBARODA',
    'HDFCLIFE', 'ABB', 'BPCL', 'PFC', 'GODREJCP', 'TATAPOWER', 'HINDALCO',
    'AMBUJACEM', 'CHOLAFIN', 'HINDZINC', 'BOSCHLTD', 'RECLTD',
    'GAIL', 'TVSMOTOR', 'ICICIPRULI', 'DIVISLAB', 'SHREECEM',
    'TECHM', 'EICHERMOT', 'BRITANNIA', 'SRF', 'CGPOWER',
    'JINDALSTEL', 'TORNTPHARM', 'MRF', 'MARICO', 'MANKIND',
]

NIFTY_MIDCAP = [
    'NATCOPHARM', 'GLENMARK', 'AUROPHARMA', 'BIOCON', 'IPCALAB',
    'LAURUSLABS', 'ALKEM', 'AJANTPHARM', 'GLAND', 'DRREDDY',
    'LUPIN', 'CIPLA', 'ABBOTINDIA',
    'RITES', 'IRCTC', 'RVNL', 'NHPC', 'SJVN', 'NBCC', 'BDL', 'PHOENIXLTD',
    'HUDCO', 'COCHINSHIP', 'GRSE', 'MAZDOCK',
    'PERSISTENT', 'COFORGE', 'MPHASIS', 'LTTS', 'TATAELXSI',
    'HAPPSTMNDS', 'TANLA',
    'DELHIVERY', 'NYKAA', 'PAYTM', 'POLICYBZR',
    'TATACONSUM', 'COLPAL', 'DABUR', 'EMAMILTD', 'JUBLFOOD',
    'PAGEIND', 'BATAINDIA', 'VOLTAS',
    'MOTHERSON', 'SONACOMS', 'EXIDEIND', 'BHARATFORG',
    'APOLLOTYRE', 'BALKRISIND', 'ASHOKLEY',
    'MUTHOOTFIN', 'MANAPPURAM', 'LICHSGFIN', 'FEDERALBNK',
    'IDFCFIRSTB', 'AUBANK', 'BANDHANBNK', 'INDIANB',
    'CUMMINSIND', 'THERMAX', 'KAYNES', 'AFFLE', 'DIXON',
    'POLYCAB', 'KEI', 'HAVELLS', 'CROMPTON', 'BLUESTARCO',
    'PIIND', 'AARTIIND', 'DEEPAKNTR', 'CLEAN', 'FLUOROCHEM',
    'ADANIGREEN', 'ADANIPOWER', 'TATAPOWER', 'TORNTPOWER', 'CESC', 'JSL',
]

ALL_TICKERS = list(dict.fromkeys(NIFTY_LARGE + NIFTY_MIDCAP))


# =============================================================================
# SENTIMENT ENGINE — FinBERT primary, TextBlob fallback
# =============================================================================

class SentimentEngine:
    """Wraps sentiment analysis with automatic fallback."""

    def __init__(self):
        self._finbert = None
        self._use_finbert = False
        self._init_engine()

    def _init_engine(self):
        """Try loading FinBERT; fall back to TextBlob."""
        try:
            from transformers import pipeline
            self._finbert = pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                top_k=None,
                truncation=True,
                max_length=512,
            )
            self._use_finbert = True
            logger.info("Sentiment engine: FinBERT (HuggingFace) loaded.")
        except Exception:
            logger.info("FinBERT not available, trying TextBlob fallback...")
            try:
                from textblob import TextBlob  # noqa: F401
                logger.info("Sentiment engine: TextBlob loaded.")
            except ImportError:
                logger.warning(
                    "Neither FinBERT nor TextBlob available. "
                    "Using keyword-based fallback."
                )

    def analyze(self, text: str) -> float:
        """
        Analyze sentiment of a text string.
        Returns a float in [-1, +1].
        """
        if not text or not text.strip():
            return 0.0

        if self._use_finbert:
            return self._analyze_finbert(text)
        else:
            return self._analyze_textblob(text)

    def _analyze_finbert(self, text: str) -> float:
        """Use FinBERT to score sentiment."""
        try:
            results = self._finbert(text[:512])
            # FinBERT returns: [{'label': 'positive', 'score': 0.9}, ...]
            if isinstance(results[0], list):
                results = results[0]

            score_map = {}
            for r in results:
                score_map[r['label']] = r['score']

            pos = score_map.get('positive', 0)
            neg = score_map.get('negative', 0)
            # Net sentiment: positive probability minus negative probability
            return round(pos - neg, 3)
        except Exception:
            return self._analyze_textblob(text)

    def _analyze_textblob(self, text: str) -> float:
        """Use TextBlob polarity as fallback."""
        try:
            from textblob import TextBlob
            blob = TextBlob(text)
            # TextBlob polarity is already in [-1, +1]
            return round(blob.sentiment.polarity, 3)
        except Exception:
            return self._analyze_keyword(text)

    def _analyze_keyword(self, text: str) -> float:
        """Last resort: keyword-based sentiment."""
        text_lower = text.lower()
        pos_words = [
            'surge', 'rally', 'gain', 'profit', 'growth', 'beat', 'upgrade',
            'strong', 'record', 'high', 'bullish', 'outperform', 'buy',
            'positive', 'boost', 'expand', 'launch', 'win', 'deal',
        ]
        neg_words = [
            'fall', 'drop', 'loss', 'decline', 'downgrade', 'weak', 'miss',
            'fraud', 'probe', 'investigation', 'sebi', 'penalty', 'sell',
            'bearish', 'crash', 'risk', 'warning', 'slump', 'cut',
        ]
        pos_count = sum(1 for w in pos_words if w in text_lower)
        neg_count = sum(1 for w in neg_words if w in text_lower)
        total = pos_count + neg_count
        if total == 0:
            return 0.0
        return round((pos_count - neg_count) / total, 3)


# =============================================================================
# EVENT TAGGING
# =============================================================================

# Compiled regex patterns for event detection
EARNINGS_PATTERN = re.compile(
    r'\b(Q[1-4]\s*results?|earnings|board\s*meeting|quarterly|annual\s*results?'
    r'|revenue|net\s*profit|EPS|dividend)\b',
    re.IGNORECASE,
)
REGULATORY_PATTERN = re.compile(
    r'\b(SEBI|investigation|fraud|probe|penalty|compliance|violation'
    r'|enforcement|insider\s*trading|money\s*laundering)\b',
    re.IGNORECASE,
)
ANALYST_PATTERN = re.compile(
    r'\b(upgrade|downgrade|target\s*price|rating|buy\s*call|sell\s*call'
    r'|outperform|underperform|accumulate|hold\s*rating)\b',
    re.IGNORECASE,
)


def tag_event(text: str) -> str:
    """Classify a headline into an event type."""
    if EARNINGS_PATTERN.search(text):
        return "earnings"
    if REGULATORY_PATTERN.search(text):
        return "regulatory"
    if ANALYST_PATTERN.search(text):
        return "analyst"
    return "general"


# =============================================================================
# NEWS FETCHER
# =============================================================================

def fetch_news_for_stock(symbol: str) -> list[dict]:
    """
    Fetch recent news articles for a stock using yfinance.
    Returns list of dicts with: title, summary, published_at, source, event_type.
    """
    ticker = yf.Ticker(f"{symbol}.NS")
    articles = []

    try:
        news_items = ticker.news
        if not news_items:
            return articles

        now = datetime.now(timezone.utc)
        cutoff_30d = now - timedelta(days=30)

        for item in news_items:
            try:
                content = item.get('content', item)

                title = content.get('title', '')
                summary = content.get('summary', '')
                pub_date_str = content.get('pubDate', content.get('displayTime', ''))

                if not title:
                    continue

                # Parse publication date
                if pub_date_str:
                    try:
                        pub_date = datetime.fromisoformat(
                            pub_date_str.replace('Z', '+00:00')
                        )
                    except (ValueError, TypeError):
                        pub_date = now
                else:
                    pub_date = now

                # Only keep articles within the last 30 days
                if pub_date < cutoff_30d:
                    continue

                # Get source
                provider = content.get('provider', {})
                source = provider.get('displayName', 'Unknown') if isinstance(provider, dict) else 'Unknown'

                # Combine title + summary for better sentiment analysis
                full_text = f"{title}. {summary}" if summary else title

                articles.append({
                    'symbol': symbol,
                    'title': title,
                    'summary': summary,
                    'full_text': full_text,
                    'published_at': pub_date.isoformat(),
                    'source': source,
                    'event_type': tag_event(full_text),
                    'days_ago': (now - pub_date).days,
                })
            except Exception:
                continue

    except Exception as e:
        logger.debug(f"Could not fetch news for {symbol}: {e}")

    return articles


# =============================================================================
# AGGREGATION — per stock per day
# =============================================================================

def aggregate_features(
    articles: list[dict],
    sentiment_engine: SentimentEngine,
    symbol: str,
) -> dict:
    """
    Given a list of articles for a single stock, compute aggregate
    sentiment features.
    """
    features = {
        'symbol': symbol,
        'sentiment_7d': 0.0,
        'sentiment_30d': 0.0,
        'num_pos_news_7d': 0,
        'num_neg_news_7d': 0,
        'num_articles_7d': 0,
        'num_articles_30d': 0,
        'has_earnings_news_7d': False,
        'has_neg_reg_news_7d': False,
        'has_analyst_news_7d': False,
        'top_headline': '',
    }

    if not articles:
        return features

    # Score each article
    scores_7d = []
    scores_30d = []

    for article in articles:
        sentiment = sentiment_engine.analyze(article['full_text'])
        days_ago = article['days_ago']

        if days_ago <= 30:
            scores_30d.append(sentiment)
            features['num_articles_30d'] += 1

        if days_ago <= 7:
            scores_7d.append(sentiment)
            features['num_articles_7d'] += 1

            if sentiment > 0.1:
                features['num_pos_news_7d'] += 1
            elif sentiment < -0.1:
                features['num_neg_news_7d'] += 1

            # Event flags
            if article['event_type'] == 'earnings':
                features['has_earnings_news_7d'] = True
            if article['event_type'] == 'regulatory' and sentiment < 0:
                features['has_neg_reg_news_7d'] = True
            if article['event_type'] == 'analyst':
                features['has_analyst_news_7d'] = True

    # Compute average sentiments
    if scores_7d:
        features['sentiment_7d'] = round(sum(scores_7d) / len(scores_7d), 3)
    if scores_30d:
        features['sentiment_30d'] = round(sum(scores_30d) / len(scores_30d), 3)

    # Store top headline (most recent)
    if articles:
        features['top_headline'] = articles[0]['title'][:100]

    return features


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def run_pipeline(tickers: list[str] | None = None):
    """Run the full news-sentiment pipeline."""
    if tickers is None:
        tickers = ALL_TICKERS

    print("=" * 70)
    print(f"  NEWS-SENTIMENT PIPELINE")
    print(f"  Scanning {len(tickers)} stocks | {datetime.now().strftime('%d-%b-%Y %H:%M')}")
    print("=" * 70)

    engine = SentimentEngine()

    all_features = []
    all_raw_articles = []

    for i, symbol in enumerate(tickers):
        if i % 20 == 0 and i > 0:
            print(f"  Processing {i}/{len(tickers)}...")

        articles = fetch_news_for_stock(symbol)

        if articles:
            all_raw_articles.extend(articles)

        features = aggregate_features(articles, engine, symbol)
        all_features.append(features)

        # Be polite to Yahoo Finance
        time.sleep(0.3)

    # Save features CSV
    features_df = pd.DataFrame(all_features)
    features_df.to_csv('news_features.csv', index=False)

    # Save raw articles for inspection
    if all_raw_articles:
        raw_df = pd.DataFrame(all_raw_articles)
        raw_df.to_csv('news_raw_articles.csv', index=False)

    # Print summary
    has_news = features_df[features_df['num_articles_7d'] > 0]
    positive = features_df[features_df['sentiment_7d'] > 0.1]
    negative = features_df[features_df['sentiment_7d'] < -0.1]
    reg_risk = features_df[features_df['has_neg_reg_news_7d'] == True]

    print(f"\n{'=' * 70}")
    print(f"  SENTIMENT SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Stocks with recent news (7d): {len(has_news)}/{len(tickers)}")
    print(f"  Positive sentiment:           {len(positive)}")
    print(f"  Negative sentiment:           {len(negative)}")
    print(f"  Regulatory risk flags:        {len(reg_risk)}")
    print(f"  Total articles processed:     {len(all_raw_articles)}")

    # Top positive sentiment stocks
    if not positive.empty:
        print(f"\n  TOP POSITIVE SENTIMENT (7d):")
        top_pos = positive.nlargest(5, 'sentiment_7d')
        for _, row in top_pos.iterrows():
            print(f"    {row['symbol']:<15s} sentiment: {row['sentiment_7d']:+.3f}  "
                  f"({row['num_articles_7d']} articles)  {row['top_headline'][:50]}")

    # Negative sentiment stocks
    if not negative.empty:
        print(f"\n  NEGATIVE SENTIMENT (7d):")
        top_neg = negative.nsmallest(5, 'sentiment_7d')
        for _, row in top_neg.iterrows():
            print(f"    {row['symbol']:<15s} sentiment: {row['sentiment_7d']:+.3f}  "
                  f"({row['num_articles_7d']} articles)  {row['top_headline'][:50]}")

    # Regulatory flags
    if not reg_risk.empty:
        print(f"\n  REGULATORY RISK FLAGS:")
        for _, row in reg_risk.iterrows():
            print(f"    {row['symbol']:<15s} {row['top_headline'][:60]}")

    print(f"\n  Saved: news_features.csv ({len(features_df)} stocks)")
    print(f"  Saved: news_raw_articles.csv ({len(all_raw_articles)} articles)")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        # Debug mode with specified tickers
        run_pipeline(sys.argv[1:])
    else:
        run_pipeline()
