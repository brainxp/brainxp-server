from fastapi import HTTPException, status


class AppError(HTTPException):
    code = "error"

    def __init__(self, detail: str, *, status_code: int = 400, code: str | None = None):
        super().__init__(status_code=status_code, detail={"code": code or self.code, "message": detail})


class Unauthorized(AppError):
    def __init__(self, detail: str = "Kredensial tidak sah."):
        super().__init__(detail, status_code=status.HTTP_401_UNAUTHORIZED, code="unauthorized")


class Forbidden(AppError):
    def __init__(self, detail: str = "Tidak berwenang atas sumber daya ini."):
        super().__init__(detail, status_code=status.HTTP_403_FORBIDDEN, code="forbidden")


class NotFound(AppError):
    def __init__(self, detail: str = "Tidak ditemukan."):
        super().__init__(detail, status_code=status.HTTP_404_NOT_FOUND, code="not_found")


class Conflict(AppError):
    def __init__(self, detail: str, code: str = "conflict"):
        super().__init__(detail, status_code=status.HTTP_409_CONFLICT, code=code)


class TooLarge(AppError):
    def __init__(self, detail: str = "Berkas melampaui batas ukuran."):
        super().__init__(detail, status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, code="too_large")


class RateLimited(AppError):
    def __init__(self, detail: str = "Kuota harian sudah terpakai."):
        super().__init__(detail, status_code=status.HTTP_429_TOO_MANY_REQUESTS, code="rate_limited")


class Invalid(AppError):
    def __init__(self, detail: str, code: str = "invalid"):
        super().__init__(detail, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, code=code)


class LLMRefused(AppError):

    def __init__(self, category: str | None = None):
        super().__init__(
            f"Materi ini tidak dapat diproses oleh layanan AI (kategori: {category or 'tidak disebut'}).",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="llm_refused",
        )
