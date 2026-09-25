class ApiError(Exception):
    """Any error we want to send to the client as a clean, structured JSON response."""

    def __init__(self, status_code, code, message, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []

    def to_body(self):
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}
