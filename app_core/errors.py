class AppError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ValidationError(AppError):
    status_code = 422


class InvalidTaskTypeError(AppError):
    pass


class InvalidDimensionError(AppError):
    pass


class NotFoundError(AppError):
    status_code = 404


class UnauthorizedError(AppError):
    status_code = 401
