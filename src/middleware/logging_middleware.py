import time
import json
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from src.utils.log_manager import log_manager

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get('user-agent', '')[:500]

        user_id = None
        username = None
        if hasattr(request.state, 'user'):
            user_id = getattr(request.state.user, 'user_id', None)
            username = getattr(request.state.user, 'username', None)

        action = f"{request.method} {request.url.path}"
        resource = self._extract_resource(request.url.path)
        method = request.method
        path = request.url.path

        request_params = {}
        if method in ['POST', 'PUT', 'PATCH']:
            try:
                body = await request.body()
                if body:
                    request_params = {'body': json.loads(body.decode('utf-8')) if body else {}}
            except:
                pass

        query_params = dict(request.query_params)
        if query_params:
            request_params['query'] = query_params

        response = None
        error_message = None
        try:
            response = await call_next(request)
            execution_time = (time.time() - start_time) * 1000

            await log_manager.log(
                action=action,
                user_id=user_id,
                username=username,
                resource=resource,
                method=method,
                path=path,
                ip_address=client_ip,
                user_agent=user_agent,
                request_params=request_params,
                response_status=response.status_code if response else None,
                execution_time=execution_time
            )

            return response
        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            error_message = str(e)

            await log_manager.log(
                action=action,
                user_id=user_id,
                username=username,
                resource=resource,
                method=method,
                path=path,
                ip_address=client_ip,
                user_agent=user_agent,
                request_params=request_params,
                response_status=500,
                error_message=error_message,
                execution_time=execution_time
            )
            raise

    def _extract_resource(self, path: str) -> str:
        parts = path.strip('/').split('/')
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
        return parts[0] if parts else 'unknown'
