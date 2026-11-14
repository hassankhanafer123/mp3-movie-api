# MP3 Movie API

This FastAPI application stores a single movie collection in SQLite and serves it through a small REST API. `main.py` defines the endpoints, `src/database.py` creates connections and the `movies` table, `src/storage.py` reads and writes rows with SQL, `src/cache.py` caches responses in FakeRedis, and `data_pipeline/` holds the MP1 validation and cleaning functions. `POST /upload` checks that a CSV has exactly the columns `title`, `release_year`, `rating`, and `genre`, then replaces the whole table in one SQLite transaction. `GET /movies` returns movies in id order with a total count, and each response is cached per `limit` for 90 seconds so repeated requests skip the database. `GET /movies/search` is not cached and filters by minimum rating with SQL, sorting by rating and then id. `POST /movies/process` loads the stored movies, runs validation, duplicate removal, missing-value handling, and outlier removal, and saves the cleaned result back to SQLite. After every successful upload or processing step, the cache is cleared so the next retrieval reflects the new data. Because the data lives in `data/movies.db`, it persists across server restarts.

## Run the API

```bash
python -m uvicorn main:app --reload
```

Then open http://127.0.0.1:8000/docs.

## Run the tests

```bash
python -m pytest tests -v
```

## Sample processing request

After uploading `fixtures/sample_movies.csv`, send `POST /movies/process` with:

```json
{
  "validation": {
    "required_columns": ["title", "release_year", "rating", "genre"],
    "numeric_columns": ["release_year", "rating"]
  },
  "processing": {
    "remove_duplicates": true,
    "missing": {"enabled": true, "axis": "rows"},
    "outliers": {
      "enabled": true,
      "columns": ["rating"],
      "method": "iqr",
      "threshold": 1.5
    }
  }
}
```

Expected result:

```json
{
  "validation_rows_removed": 0,
  "cleaning_report": {
    "rows_before": 20,
    "rows_after": 16,
    "rows_removed": 4,
    "columns_before": 4,
    "columns_after": 4,
    "columns_removed": 0
  }
}
```
