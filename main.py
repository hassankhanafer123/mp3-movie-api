import io
import logging
from pathlib import Path
import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from src import (
    HealthResponse,
    MovieDataResponse,
    MovieProcessingReport,
    MovieStorage,
    MovieUploadInfo,
    ProcessConfig,
    log_requests,
    setup_logging,
)
from src.storage import MOVIE_COLUMNS
from data_pipeline import create_cleaning_report, process_data, validate_dataframe

setup_logging(verbose=True)
logger = logging.getLogger(__name__)

app = FastAPI(title="Movie API", version="1.0.0")
app.middleware("http")(log_requests)
storage = MovieStorage()


@app.get("/health", response_model=HealthResponse)
def health_check():
    """Return the application status and version."""
    return HealthResponse(status="ok", version="1.0.0")


@app.post("/upload", response_model=MovieUploadInfo)
async def upload_movies(file: UploadFile = File(...)):
    """Read a movie CSV and replace the stored collection."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".csv":
        logger.warning("Unsupported file format: %s", suffix)
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    contents = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(contents))
    except pd.errors.EmptyDataError:
        logger.warning("Empty CSV upload: %s", file.filename)
        raise HTTPException(status_code=400, detail="The uploaded CSV file is empty.")
    except pd.errors.ParserError:
        logger.warning("Could not parse CSV: %s", file.filename)
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid CSV.")
    except UnicodeDecodeError:
        logger.warning("Could not decode CSV: %s", file.filename)
        raise HTTPException(status_code=400, detail="The CSV must be UTF-8 encoded.")

    if sorted(df.columns) != sorted(MOVIE_COLUMNS):
        logger.warning("Wrong columns: %s", list(df.columns))
        raise HTTPException(
            status_code=400,
            detail=f"CSV must have exactly these columns: {MOVIE_COLUMNS}",
        )
    if df.empty:
        logger.warning("CSV has no data rows: %s", file.filename)
        raise HTTPException(status_code=400, detail="The CSV has no data rows.")

    df = df[MOVIE_COLUMNS]

    storage.save(df)
    logger.info("Uploaded movies: filename=%s, rows=%d", file.filename, len(df))
    return MovieUploadInfo(
        filename=file.filename,
        rows=len(df),
        columns=len(df.columns),
        column_names=list(df.columns),
    )


@app.get("/movies", response_model=MovieDataResponse)
def get_movies(limit: int = Query(default=100, ge=1)):
    """Return up to limit movies and the total stored count."""
    records = storage.select_columns(MOVIE_COLUMNS, limit)
    total_rows = storage.count_movies()
    logger.info("Retrieved movies: returned_rows=%d", len(records))
    return {"data": records, "total_rows": total_rows}


@app.get("/movies/search", response_model=list[dict])
def query_movies(
    columns: list[str] = Query(default=["title"]),
    min_rating: float = Query(default=0, ge=0, le=10),
    limit: int = Query(default=100, ge=1),
):
    """Return selected fields for movies with rating >= min_rating."""
    try:
        records = storage.query_movies(columns, min_rating, limit)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    logger.info(
        "Queried movies: columns=%s, min_rating=%s, returned_rows=%d",
        columns, min_rating, len(records),
    )
    return records


@app.post("/movies/process", response_model=MovieProcessingReport)
def process_movies(config: ProcessConfig):
    """Validate and process the stored movies, then save the result."""
    df = storage.get()
    if df.empty:
        logger.warning("No movies to process")
        raise HTTPException(status_code=400, detail="No movies stored. Upload a CSV first.")

    config_dict = config.model_dump()
    validation = config_dict["validation"]

    for col in validation["numeric_columns"]:
        if col not in df.columns:
            logger.warning("Numeric column missing: %s", col)
            raise HTTPException(status_code=400, detail=f"Numeric column missing: {col}")

    try:
        validated = validate_dataframe(
            df, validation["required_columns"], validation["numeric_columns"]
        )
        validation_removed = len(df) - len(validated)
        logger.info("Validated movies: rows_removed=%d", validation_removed)

        before_processing = validated.copy()
        processed = process_data(validated, config_dict)
    except ValueError as error:
        logger.warning("Processing failed: error=%s", error)
        raise HTTPException(status_code=400, detail=str(error))

    report = create_cleaning_report(before_processing, processed)
    storage.save(processed)
    logger.info(
        "Processed movies: validation_removed=%d, rows_before=%d, rows_after=%d",
        validation_removed, report["rows_before"], report["rows_after"],
    )
    return {
        "validation_rows_removed": validation_removed,
        "cleaning_report": report,
    }
