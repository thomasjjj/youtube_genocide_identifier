import sqlite3
import json
import argparse
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from openai import OpenAI

# Import configuration settings
from config import OPENAI_API_KEY, MODEL, DB_PATH
# Import system prompts
from system_prompt import ANALYSIS_SCHEMA, construct_genocide_analysis_prompt

# Configure module-level logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def sanitize_schema(schema: Any) -> Any:
    """
    Recursively strip unsupported keywords and ensure strict object constraints for OpenAI API.
    """
    if isinstance(schema, dict):
        new_schema: Dict[str, Any] = {}
        for key, value in schema.items():
            if key in ("pattern", "patternProperties"):
                continue
            new_schema[key] = sanitize_schema(value)
        if new_schema.get("type") == "object" and "properties" in new_schema:
            new_schema.setdefault("additionalProperties", False)
        return new_schema
    if isinstance(schema, list):
        return [sanitize_schema(item) for item in schema]
    return schema


class TranscriptAnalyzer:
    """
    Analyzes YouTube transcripts with OpenAI's API to detect incitement to genocide.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = None):
        """
        Initialize the TranscriptAnalyzer with OpenAI API key.

        Args:
            api_key (str, optional): OpenAI API key. If None, uses from config.
            model (str, optional): OpenAI model to use. If None, uses from config.
        """
        # Use provided API key or default from config
        self.api_key = api_key or OPENAI_API_KEY
        self.model = model or MODEL

        # Initialize OpenAI client
        self.client = OpenAI(api_key=self.api_key)

        # Connect to database
        self.db_path = DB_PATH
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Database not found at {self.db_path}. Run the transcript extraction script first.")

        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # This allows accessing columns by name

    def close(self):
        """Close the database connection."""
        if hasattr(self, 'conn'):
            self.conn.close()

    def get_transcript_by_id(self, record_id: int) -> Optional[Dict[str, Any]]:
        """Get a transcript by its database ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM transcripts WHERE id = ?", (record_id,))
        row = cursor.fetchone()

        if not row:
            return None

        return dict(row)

    def get_transcript_by_video_id(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent transcript for a video ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM transcripts WHERE video_id = ? ORDER BY extraction_date DESC LIMIT 1",
            (video_id,)
        )
        row = cursor.fetchone()

        if not row:
            return None

        return dict(row)

    def list_available_transcripts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent transcripts in the database."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, video_id, video_title, channel_name, extraction_date FROM transcripts ORDER BY extraction_date DESC LIMIT ?",
            (limit,)
        )
        rows = cursor.fetchall()

        return [dict(row) for row in rows]

    async def analyze_genocide_incitement(self, transcript_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze if transcript contains incitement to genocide.

        Args:
            transcript_data: Transcript data from the database.

        Returns:
            Dict: Structured response from OpenAI.
        """
        # Get the transcript text
        transcript_text = transcript_data['transcript_text']

        # If transcript is too long, truncate it to fit within OpenAI's token limits
        max_chars = 100000  # Approximate limit to stay within token constraints
        if len(transcript_text) > max_chars:
            transcript_text = transcript_text[:max_chars] + "...[truncated]"

        # Prepare metadata for context
        metadata = f"Video: {transcript_data['video_title']}\n"
        metadata += f"Channel: {transcript_data['channel_name']}\n"

        # Create the system prompt for genocide analysis
        system_prompt = construct_genocide_analysis_prompt()

        # Prepare the query content
        user_content = f"{metadata}\nTranscript:\n{transcript_text}"

        # Sanitize the schema for OpenAI API
        strict_schema = sanitize_schema(ANALYSIS_SCHEMA)

        try:
            # Use asyncio to run the API call in a separate thread
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                response_format={
                    "type": "json_schema",
                    "schema": strict_schema
                }
            )

            # Extract the result
            parsed = getattr(response.choices[0].message, 'parsed', None)
            if parsed is None and response.choices[0].message.content:
                parsed = json.loads(response.choices[0].message.content)

            # Save the result to a separate table in the database
            self.save_analysis_result(
                transcript_data['id'],
                "Does the content incite genocide?",
                json.dumps(parsed),
                response.model,
                response.usage.total_tokens
            )

            # Add additional context to the response
            parsed.update({
                "model": response.model,
                "tokens_used": response.usage.total_tokens,
                "video_title": transcript_data['video_title'],
                "timestamp": datetime.now().isoformat()
            })

            return parsed

        except Exception as e:
            logger.error("Error calling OpenAI API: %s", e, exc_info=True)
            return {"error": str(e)}

    def save_analysis_result(self, transcript_id: int, question: str, answer: str, model: str, tokens: int):
        """Save the analysis result to the database."""
        cursor = self.conn.cursor()

        # Create analysis results table if it doesn't exist
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS analysis_results
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           transcript_id
                           INTEGER
                           NOT
                           NULL,
                           question
                           TEXT
                           NOT
                           NULL,
                           answer
                           TEXT
                           NOT
                           NULL,
                           model
                           TEXT
                           NOT
                           NULL,
                           tokens_used
                           INTEGER
                           NOT
                           NULL,
                           analysis_date
                           TIMESTAMP
                           NOT
                           NULL,
                           FOREIGN
                           KEY
                       (
                           transcript_id
                       ) REFERENCES transcripts
                       (
                           id
                       )
                           )
                       ''')

        # Insert the analysis result
        cursor.execute('''
                       INSERT INTO analysis_results
                           (transcript_id, question, answer, model, tokens_used, analysis_date)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ''', (
                           transcript_id,
                           question,
                           answer,
                           model,
                           tokens,
                           datetime.now().isoformat()
                       ))

        self.conn.commit()


async def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Analyze YouTube transcripts for incitement to genocide")
    parser.add_argument("--api-key", help="OpenAI API key (overrides config)")
    parser.add_argument("--model", help=f"OpenAI model to use (default: {MODEL})")

    # Group for selecting transcript
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List available transcripts")
    group.add_argument("--id", type=int, help="Analyze transcript by database ID")
    group.add_argument("--video-id", help="Analyze transcript by YouTube video ID")

    # Parse arguments
    args = parser.parse_args()

    try:
        # Initialize analyzer
        analyzer = TranscriptAnalyzer(api_key=args.api_key, model=args.model)

        # List available transcripts
        if args.list:
            transcripts = analyzer.list_available_transcripts()
            print("\nAvailable Transcripts:")
            print("-" * 80)
            for t in transcripts:
                print(f"ID: {t['id']} | Video ID: {t['video_id']} | Title: {t['video_title']}")
            print("-" * 80)
            print("To analyze a transcript, run the script with --id <ID> or --video-id <VIDEO_ID>")
            return

        # Get transcript by ID or video ID
        transcript_data = None
        if args.id:
            transcript_data = analyzer.get_transcript_by_id(args.id)
        elif args.video_id:
            transcript_data = analyzer.get_transcript_by_video_id(args.video_id)

        if not transcript_data:
            print("Transcript not found. Run with --list to see available transcripts.")
            return

        # Analyze for incitement to genocide
        print(f"\nAnalyzing transcript for: {transcript_data['video_title']}")
        print("Analysis type: Incitement to genocide (based on Rome Statute definition)")
        print("Sending to OpenAI...")

        result = await analyzer.analyze_genocide_incitement(transcript_data)

        if "error" in result:
            print(f"Error: {result['error']}")
            return

        # Print the result in a nice format
        print("\nAnalysis Result:")
        print("-" * 80)
        print(f"Answer: {result['answer']}")
        print(f"Reasoning: {result['reasoning']}")
        print("\nEvidence:")
        for i, evidence in enumerate(result['evidence'], 1):
            print(f"{i}. {evidence}")
        print("-" * 80)
        print(f"Model: {result['model']}")
        print(f"Tokens used: {result['tokens_used']}")

    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
    finally:
        # Clean up
        if 'analyzer' in locals():
            analyzer.close()


if __name__ == "__main__":
    asyncio.run(main())