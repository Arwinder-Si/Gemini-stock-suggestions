"""
Single source of truth for stock universes and sector mappings.
Eliminates duplication across screeners, triggers, and strategy modules.
"""

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

SMALL_CAP = [
    # High Beta / Volatile Small Caps
    'SUZLON', 'RCF', 'FACT', 'NFL', 'GSFC', 'GNFC',
    'MTNL', 'ITI', 'HMT', 'HINDCOPPER', 'NATIONALUM',
    'NMDC', 'KIOCL', 'MOIL', 'MANGCHEFER',
    'ENGINERSIN', 'RITES', 'IRCON', 'SEAMECLTD',
    'MAHABANK', 'PSB', 'J&KBANK', 'SOUTHBANK', 'KARURVYSYA',
    'EQUITASBNK', 'UJJIVANSFB', 'SURYODAY', 'ESAFSFB',
    'IRB', 'HCC', 'RVNL', 'HUDCO', 'IRFC', 'RAILTEL',
    'COCHINSHIP', 'GRSE',
    'KPITTECH', 'PERSISTENT', 'TATAELXSI', 'COFORGE',
    'PAYTM', 'DELHIVERY', 'POLICYBZR', 'NYKAA',
    'BSE', 'CDSL', 'CAMS', 'ANGELONE', 'MOTILALOFS', 'UTIAMC', 'NAM-INDIA',
    'AWL', 'NDTV', 'TRIDENT', 'IREDA',
    'IDEA', 'ZENITHEXPO',
]

SECTOR_MAP = {
    # IT
    'TCS': 'IT', 'INFY': 'IT', 'HCLTECH': 'IT', 'WIPRO': 'IT', 'TECHM': 'IT',
    'PERSISTENT': 'IT', 'COFORGE': 'IT', 'MPHASIS': 'IT', 'LTTS': 'IT',
    'TATAELXSI': 'IT', 'HAPPSTMNDS': 'IT', 'TANLA': 'IT', 'KPITTECH': 'IT',
    # Pharma
    'SUNPHARMA': 'Pharma', 'DRREDDY': 'Pharma', 'CIPLA': 'Pharma', 'LUPIN': 'Pharma',
    'DIVISLAB': 'Pharma', 'NATCOPHARM': 'Pharma', 'GLENMARK': 'Pharma',
    'AUROPHARMA': 'Pharma', 'BIOCON': 'Pharma', 'IPCALAB': 'Pharma',
    'LAURUSLABS': 'Pharma', 'ALKEM': 'Pharma', 'AJANTPHARM': 'Pharma',
    'GLAND': 'Pharma', 'ABBOTINDIA': 'Pharma', 'TORNTPHARM': 'Pharma',
    'MANKIND': 'Pharma',
    # Banking / Financial
    'HDFCBANK': 'Banking', 'ICICIBANK': 'Banking', 'SBIN': 'Banking',
    'KOTAKBANK': 'Banking', 'AXISBANK': 'Banking', 'PNB': 'Banking',
    'BANKBARODA': 'Banking', 'FEDERALBNK': 'Banking', 'IDFCFIRSTB': 'Banking',
    'AUBANK': 'Banking', 'BANDHANBNK': 'Banking', 'INDIANB': 'Banking',
    'MAHABANK': 'Banking', 'PSB': 'Banking', 'J&KBANK': 'Banking',
    'SOUTHBANK': 'Banking', 'KARURVYSYA': 'Banking', 'EQUITASBNK': 'Banking',
    'UJJIVANSFB': 'Banking', 'SURYODAY': 'Banking', 'ESAFSFB': 'Banking',
    'BAJFINANCE': 'Financials', 'BAJAJFINSV': 'Financials', 'CHOLAFIN': 'Financials',
    'MUTHOOTFIN': 'Financials', 'MANAPPURAM': 'Financials', 'LICHSGFIN': 'Financials',
    'PFC': 'Financials', 'RECLTD': 'Financials', 'BSE': 'Financials',
    'CDSL': 'Financials', 'CAMS': 'Financials', 'ANGELONE': 'Financials',
    'MOTILALOFS': 'Financials', 'UTIAMC': 'Financials', 'NAM-INDIA': 'Financials',
    # Auto
    'MARUTI': 'Auto', 'BAJAJ-AUTO': 'Auto', 'M&M': 'Auto', 'TVSMOTOR': 'Auto',
    'EICHERMOT': 'Auto', 'MOTHERSON': 'Auto', 'SONACOMS': 'Auto',
    'EXIDEIND': 'Auto', 'BHARATFORG': 'Auto', 'APOLLOTYRE': 'Auto',
    'BALKRISIND': 'Auto', 'ASHOKLEY': 'Auto', 'BOSCHLTD': 'Auto',
    # Energy / Power / Infra
    'RELIANCE': 'Energy', 'ONGC': 'Energy', 'NTPC': 'Power', 'POWERGRID': 'Power',
    'IOC': 'Energy', 'BPCL': 'Energy', 'TATAPOWER': 'Power', 'GAIL': 'Energy',
    'ADANIGREEN': 'Power', 'ADANIPOWER': 'Power', 'TORNTPOWER': 'Power',
    'CESC': 'Power', 'SUZLON': 'Power', 'IREDA': 'Power', 'SJVN': 'Power',
    'NHPC': 'Power', 'LT': 'Infra', 'DLF': 'Real Estate', 'PHOENIXLTD': 'Real Estate',
    'IRB': 'Infra', 'HCC': 'Infra', 'RVNL': 'Infra', 'HUDCO': 'Infra',
    'IRFC': 'Infra', 'RAILTEL': 'Infra', 'RITES': 'Infra', 'IRCON': 'Infra',
    'NBCC': 'Infra', 'ENGINERSIN': 'Infra',
    # Metals
    'JSWSTEEL': 'Metals', 'TATASTEEL': 'Metals', 'COALINDIA': 'Metals',
    'HINDALCO': 'Metals', 'HINDZINC': 'Metals', 'JINDALSTEL': 'Metals',
    'JSL': 'Metals', 'NMDC': 'Metals', 'NATIONALUM': 'Metals',
    'HINDCOPPER': 'Metals', 'KIOCL': 'Metals', 'MOIL': 'Metals',
    # Defense
    'HAL': 'Defense', 'BEL': 'Defense', 'COCHINSHIP': 'Defense',
    'GRSE': 'Defense', 'MAZDOCK': 'Defense', 'BDL': 'Defense',
    # Consumer
    'ITC': 'FMCG', 'HINDUNILVR': 'FMCG', 'NESTLEIND': 'FMCG',
    'TATACONSUM': 'FMCG', 'COLPAL': 'FMCG', 'DABUR': 'FMCG',
    'EMAMILTD': 'FMCG', 'JUBLFOOD': 'FMCG', 'GODREJCP': 'FMCG',
    'MARICO': 'FMCG', 'BRITANNIA': 'FMCG', 'TITAN': 'Consumer',
    'ASIANPAINT': 'Consumer', 'PIDILITIND': 'Chemicals', 'TRENT': 'Retail',
    'INDIGO': 'Aviation', 'DMART': 'Retail', 'AWL': 'FMCG',
}


def get_universe_symbols(universe_type: str = "large") -> list[str]:
    """Get list of clean ticker symbols for specified universe."""
    if universe_type == "small":
        return list(dict.fromkeys(SMALL_CAP))
    elif universe_type == "large":
        return list(dict.fromkeys(NIFTY_LARGE + NIFTY_MIDCAP))
    else:
        return list(dict.fromkeys(NIFTY_LARGE + NIFTY_MIDCAP + SMALL_CAP))
