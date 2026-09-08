from flask import jsonify


class APIError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def success(data=None, status=200, **extra):
    return jsonify(success=True, data=data if data is not None else {}, **extra), status
