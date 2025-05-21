# YouTube Incitement of Genocide Analysis Toolkit
![image](https://github.com/user-attachments/assets/40517747-572a-4405-a537-8a6fdc573ace)
A specialised Python tool designed to detect potential incitement to genocide in YouTube video transcripts. This toolkit extracts YouTube video transcripts and analyses them against international legal standards for genocide incitement using OpenAI's language models.

The intent of this tool is to enable media monitors and analysts to have rapid assessments of potentially problematic materials disseminated on YouTube. This includes news broadcasts and unofficial videos. It streamlines the analysis which typically requires a person to watch and transcribe hours of footage - most of which is not relevant. 

This is an early public version of the tool and it does require further work to make it as accessible and accurate as possible. 


It takes the official definition from the Rome Statute:

```python
prompt = """
    <instruction>
    You are a specialized legal analysis tool that evaluates content to determine if it qualifies 
    as incitement to genocide according to international law standards.

    Your task is to carefully analyze the provided transcript and determine whether it contains 
    content that would qualify as incitement to genocide. Answer with "Yes", "No", or 
    "Cannot determine".

    Use the following definitions from international law:

    DEFINITION OF GENOCIDE IN THE CONVENTION: 
    The current definition of Genocide is set out in Article II of the Genocide Convention: 
    Genocide means any of the following acts committed with intent to destroy, in whole or in part, 
    a national, ethnical, racial or religious group, as such: 
    (a) Killing members of the group; 
    (b) Causing serious bodily or mental harm to members of the group; 
    (c) Deliberately inflicting on the group conditions of life calculated to bring about its 
        physical destruction in whole or in part; 
    (d) Imposing measures intended to prevent births within the group; 
    (e) Forcibly transferring children of the group to another group.

    THE SPECIFIC "INTENT" REQUIREMENT OF THE CRIME OF GENOCIDE: 
    The definition of Genocide is made up of two elements, the physical element — the acts committed; 
    and the mental element — the intent. Intent is the most difficult element to determine. 
    To constitute genocide, there must be a proven intent on the part of perpetrators to physically 
    destroy a national, ethnical, racial or religious group. Cultural destruction does not suffice, 
    nor does an intention to simply disperse a group, though this may constitute a crime against 
    humanity as set out in the Rome Statute. It is this special intent, or dolus specialis, that 
    makes the crime of genocide so unique. To constitute genocide, it also needs to be established 
    that the victims are deliberately targeted — not randomly — because of their real or perceived 
    membership of one of the four groups protected under the Convention. This means that the target 
    of destruction must be the group, as such, or even a part of it, but not its members as individuals.

    To analyze for INCITEMENT to genocide, look for content that:
    1. Directly and publicly calls for acts that would constitute genocide
    2. Creates or inflames hatred toward a protected group with explicit or implicit calls for their destruction
    3. Dehumanizes a protected group in a way that could reasonably be interpreted as encouraging violence against them
    4. Contains coded language that, in context, would be understood as calling for genocide

    Follow these steps in your analysis:
    1. Thoroughly review the entire transcript.
    2. Identify any specific passages or statements that relate to protected groups.
    3. Evaluate if these passages meet the legal threshold for incitement to genocide.
    4. If there is insufficient evidence to make a determination, answer "Cannot determine".
    5. Explain your reasoning clearly, referencing specific parts of the transcript.
    6. Include direct quotes from the transcript as evidence.

    Your response must follow the exact JSON schema provided, with no additional commentary.
    </instruction>

    <output_format>
    Return your analysis as a JSON object with the following structure:
    """
```

**The goals of this tool are:**
- to create an efficient means to identifying incitement of genocide on YouTube
- to bypass the need for audio transcription tools (since YouTube has already generated the transcripts)
- to generate a labelled dataset of transcripts that can then be used to train a more efficient and environmentally friendly model
- to make those spreading hate accountable

**This tool is designed to be convertable:**
- changes to the system prompt will allow it to analyse any question you can think of
- it is made to be as modular as possible so you can run analysis on existing databases or make a database without analysis

## Features

- **Transcript Extraction**: Download and store YouTube video transcripts using the YouTube Transcript API
- **Metadata Retrieval**: Fetch video titles and channel names without requiring YouTube API credentials
- **Genocide Analysis**: Structured evaluation of content against Rome Statute criteria for incitement to genocide
- **Persistence**: Store transcripts and analysis results in SQLite with file-based backups
- **User-Friendly CLI**: Modern command-line interface with Rich text formatting

![image](https://github.com/user-attachments/assets/c29106e6-fe1e-482d-9726-b0354f6a20c8)

![image](https://github.com/user-attachments/assets/0bf789c5-b373-44c2-a2e9-c8b535e196c8)

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


## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Disclaimer

This tool is designed for research and content moderation purposes. Analysis results should be reviewed by qualified human moderators and should not be used as the sole basis for content decisions.