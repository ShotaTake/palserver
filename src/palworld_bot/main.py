"""Application entry point."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

from palworld_bot.config import ConfigError, load_config
from palworld_bot.discord_app import PalworldBotClient
from palworld_bot.services.server_manager import ServerManager


def main() -> None:
    """Load configuration and run the Discord bot."""
    load_dotenv()
    try:
        config = load_config(os.environ)
    except ConfigError as exc:
        raise SystemExit(f"configuration error: {exc}") from None
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    manager = ServerManager(config)
    client = PalworldBotClient(config, manager)
    client.run(config.discord_bot_token, log_handler=None)


if __name__ == "__main__":
    main()
