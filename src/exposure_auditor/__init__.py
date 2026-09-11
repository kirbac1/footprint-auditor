def main() -> None:
    import uvicorn

    uvicorn.run("exposure_auditor.main:create_app", factory=True, host="127.0.0.1", port=8000)
