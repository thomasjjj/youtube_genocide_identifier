import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Configure module-level logger
logger = logging.getLogger(__name__)

# Project paths
BASE_DIR = Path(__file__).parent.absolute()
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "youtube_transcripts.db"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
RESULTS_DIR = DATA_DIR / "individual_results"  # New directory for results


# Ensure required directories exist
def ensure_dirs_exist():
    """Create necessary directories if they don't exist."""
    for directory in [DATA_DIR, TRANSCRIPTS_DIR, RESULTS_DIR]:  # Added RESULTS_DIR
        # Make sure directory is a Path object
        directory = Path(directory) if isinstance(directory, str) else directory
        directory.mkdir(parents=True, exist_ok=True)

    logger.info(f"Ensured project directories exist: {DATA_DIR}, {TRANSCRIPTS_DIR}, {RESULTS_DIR}")


# Environment variables management
def load_env_vars():
    """Load environment variables from .env file if it exists."""
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logger.info(f"Loaded environment variables from {env_path}")
        return True
    return False


def get_openai_api_key():
    """
    Get the OpenAI API key from environment variables or prompt the user.

    Returns:
        str: The OpenAI API key
    """
    # Check if API key is already in environment
    api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        # If .env file exists but doesn't have the key, or if .env doesn't exist
        env_path = BASE_DIR / ".env"

        # Prompt the user for the API key
        api_key = input("Please enter your OpenAI API key: ").strip()

        if not api_key:
            raise ValueError("OpenAI API key is required to use this application.")

        # Save the key to .env file
        with open(env_path, "a+") as f:
            f.seek(0)  # Go to beginning of file to check if we need a newline
            content = f.read()
            if content and not content.endswith("\n"):
                f.write("\n")  # Add newline if file exists and doesn't end with one
            f.write(f"OPENAI_API_KEY={api_key}\n")

        # Set the environment variable for current session
        os.environ["OPENAI_API_KEY"] = api_key
        logger.info("Saved OpenAI API key to .env file")

    return api_key


# Default OpenAI model settings
DEFAULT_MODEL = "gpt-4o-mini"


# Application settings
def get_app_settings():
    """Get application settings from environment variables or use defaults."""
    return {
        "openai_api_key": get_openai_api_key(),
        "model": os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
        "db_path": os.environ.get("DB_PATH", str(DB_PATH)),
        "transcripts_dir": os.environ.get("TRANSCRIPTS_DIR", str(TRANSCRIPTS_DIR)),
        "results_dir": os.environ.get("RESULTS_DIR", str(RESULTS_DIR))  # Add results_dir to settings
    }


# Initialize environment when module is imported
load_env_vars()
ensure_dirs_exist()

# Export all settings as module-level variables for easy import
APP_SETTINGS = get_app_settings()
OPENAI_API_KEY = APP_SETTINGS["openai_api_key"]
MODEL = APP_SETTINGS["model"]
# Make sure RESULTS_DIR is a Path object when exported
RESULTS_DIR = Path(APP_SETTINGS["results_dir"])