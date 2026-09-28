# BITS Academic Course Recommender

Python course recommendation application using the supplied BITS Bulletin, Academic
Regulations, timetable and course handouts.

## Requirements

- Python 3.10 or newer
- Poppler (`pdftotext`) for rebuilding extracted data

## Run

```bash
python app.py
```

This starts an interactive terminal menu. The first run asks for the student profile
and saves it to `student_profile.json`.

Run a single query with the saved profile:

```bash
python app.py --query "Suggest AI DELs with no quiz"
```

Print the full result as JSON:

```bash
python app.py --query "Suggest AI DELs" --json
```

Create or update the profile:

```bash
python app.py --profile
```

## Gemini query parsing

```bash
export GEMINI_API_KEY="your-key"
export GEMINI_MODEL="gemini-3.8-flash"
python app.py
```

`GEMINI_MODEL` is optional. If `GEMINI_API_KEY` is not set, the application uses its local query parser.
Academic validation is handled locally in both cases.

## Rebuild data

```bash
python constraints.py
python handout_parser.py
```

Generated files are stored in `academic_data/` and `temp.json`.

## Test

```bash
python -m unittest -v
```

## Main files

- `app.py`: terminal interface and profile management
- `agent.py`: query parsing workflow
- `recommender.py`: eligibility checks and course ranking
- `constraints.py`: Bulletin, regulations and timetable extraction
- `handout_parser.py`: handout extraction

CDC, DEL and HUEL classifications come from `programme_categories.json`. OPEL
results are withheld when the supplied data cannot establish the classification.
