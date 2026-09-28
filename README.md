# BITS Academic Course Recommender

Course recommendation dashboard using the supplied BITS Bulletin, Academic
Regulations, timetable and course handouts.

## Requirements

- Python 3.10 or newer
- Poppler (`pdftotext`) for rebuilding extracted data

## Run

```bash
python app.py
```

Open <http://127.0.0.1:8000>.

To use a different port:

```bash
python app.py --port 8080
```

Profiles are saved to `student_profile.json`.

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

- `app.py`: web server and API
- `agent.py`: query parsing workflow
- `recommender.py`: eligibility checks and course ranking
- `constraints.py`: Bulletin, regulations and timetable extraction
- `handout_parser.py`: handout extraction
- `web/`: dashboard files

CDC, DEL and HUEL classifications come from `programme_categories.json`. OPEL
results are withheld when the supplied data cannot establish the classification.
