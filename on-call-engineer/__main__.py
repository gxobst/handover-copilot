"""Entry point for executing on-call poller module."""

import sys
from poll_alerts import main

if __name__ == "__main__":
    sys.exit(main())
