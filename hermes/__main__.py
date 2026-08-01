"""Enable ``python -m hermes`` as an alias for the CLI."""

import sys

from hermes.cli import main

if __name__ == "__main__":
    sys.exit(main())
