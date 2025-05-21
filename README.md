# YouTube Genocide Analysis Toolkit

A specialised Python tool designed to detect potential incitement to genocide in YouTube video transcripts. This toolkit extracts YouTube video transcripts and analyzes them against international legal standards for genocide incitement using OpenAI's language models.

## Features

- **Transcript Extraction**: Download and store YouTube video transcripts using the YouTube Transcript API
- **Metadata Retrieval**: Fetch video titles and channel names without requiring YouTube API credentials
- **Genocide Analysis**: Structured evaluation of content against Rome Statute criteria for incitement to genocide
- **Persistence**: Store transcripts and analysis results in SQLite with file-based backups
- **User-Friendly CLI**: Modern command-line interface with Rich text formatting

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/youtube-genocide-analysis
   cd youtube-genocide-analysis
   ```

2. Create a virtual environment and install dependencies:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the project root with your OpenAI API key:
   ```
   OPENAI_API_KEY=your_openai_api_key_here
   ```

## Requirements

- Python 3.8+
- OpenAI API key
- Dependencies (see requirements.txt):
  - openai
  - youtube-transcript-api
  - typer
  - rich
  - pydantic-settings
  - python-dotenv
  - pytube (as fallback for metadata)
  - yt-dlp (preferred for metadata, if installed)

## Usage

### Command Line Interface

The toolkit has an intuitive command-line interface with several commands:

#### Quick Start (Full Pipeline)

```bash
# Interactive mode (prompts for URL)
python genocide_detect.py

# Direct analysis (URL as argument)
python genocide_detect.py https://www.youtube.com/watch?v=VIDEO_ID

# Direct analysis (video ID only)
python genocide_detect.py VIDEO_ID
```

#### Extract Only

```bash
# Extract transcript without analysis
python genocide_detect.py extract https://www.youtube.com/watch?v=VIDEO_ID

# Overwrite existing transcript
python genocide_detect.py extract https://www.youtube.com/watch?v=VIDEO_ID --overwrite
```

#### Analysis Control

```bash
# Full analysis with cache control flags
python genocide_detect.py analyze https://www.youtube.com/watch?v=VIDEO_ID --force-extract --force-analysis

# List available transcripts in the database
python genocide_detect.py list --limit 20
```

### Analysis Results

The analysis returns a structured verdict with three components:

- **answer**: "Yes", "No", or "Cannot determine"
- **reasoning**: Detailed explanation of the determination
- **evidence**: List of quotes from the transcript supporting the analysis

Results are saved in JSON format to the `data/individual_results` directory and stored in the SQLite database.

## Project Structure

```
.
├── config.py                   # Centralized settings & path management
├── genocide_detect.py          # Main Typer CLI application 
├── src/
│   ├── gpt.py                  # TranscriptAnalyzer with OpenAI integration
│   ├── system_prompt.py        # Genocide analysis prompt template
│   ├── youtube_transcript.py   # Transcript download and storage
│   └── youtube_metadata.py     # Video metadata retrieval
├── data/                       # Created at runtime
│   ├── transcripts/            # Text files of downloaded transcripts
│   ├── individual_results/     # JSON files of analysis results
│   └── youtube_transcripts.db  # SQLite database
```

## Configuration

The application uses Pydantic Settings for configuration management:

- **OpenAI Settings**:
  - `OPENAI_API_KEY`: Your OpenAI API key (required)
  - `OPENAI_MODEL`: Model to use (default: "gpt-4o-mini")

- **Storage Settings** (can be overridden via environment variables):
  - `DB_PATH`: Path to SQLite database
  - `TRANSCRIPTS_DIR`: Directory for transcript text files
  - `RESULTS_DIR`: Directory for analysis result JSON files

## Genocide Analysis Framework

The analysis evaluates transcripts against international legal standards for genocide incitement, specifically:

1. Definition of genocide from the Convention on the Prevention and Punishment of the Crime of Genocide
2. Special intent requirement (dolus specialis) from the Rome Statute
3. Criteria for incitement including direct calls for destructive acts, dehumanization, and inflammatory rhetoric

## Advanced Usage

### Using as a Python Library

You can import and use components directly in your Python code:

```python
from src.youtube_transcript import extract_video_id, fetch_transcript, save_transcript
from src.gpt import TranscriptAnalyzer
import asyncio

# Extract transcript
video_id = extract_video_id("https://www.youtube.com/watch?v=VIDEO_ID")
transcript = fetch_transcript(video_id)
file_path, saved = save_transcript(transcript, video_id)

# Analyze transcript
analyzer = TranscriptAnalyzer()
transcript_record = analyzer.get_transcript_by_video_id(video_id)
verdict = asyncio.run(analyzer.analyze(transcript_record))
print(verdict.model_dump(indent=2))
```

## License

[Insert your license information here]

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Disclaimer

This tool is designed for research and content moderation purposes. Analysis results should be reviewed by qualified human moderators and should not be used as the sole basis for content decisions.