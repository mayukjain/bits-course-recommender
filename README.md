# BITS Academic Course Recommender

Python course recommendation application using the supplied BITS Bulletin, Academic
Regulations, timetable and course handouts.

## Requirements

- Python 3.10 or newer
- Poppler (`pdftotext`) for rebuilding extracted data

Install the Python dependency:

```bash
python -m pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

The browser dashboard contains the student profile form and course search. Profiles
are saved locally to `student_profile.json`.

## Gemini query parsing

```bash
export GEMINI_API_KEY="your-key"
export GEMINI_MODEL="gemini-3.8-flash"
streamlit run app.py
```

The key can also be entered in the dashboard sidebar. `GEMINI_MODEL` is optional.
If no key is provided, the application uses its local query parser.

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

- `app.py`: Streamlit dashboard and profile management
- `agent.py`: query parsing workflow
- `recommender.py`: eligibility checks and course ranking
- `constraints.py`: Bulletin, regulations and timetable extraction
- `handout_parser.py`: handout extraction

CDC, DEL and HUEL classifications come from `programme_categories.json`. OPEL
results are withheld when the supplied data cannot establish the classification.
