"""HTTP boundary for information digestion and integration registries."""
from __future__ import annotations

import io
import json

import connection_registry
import db
import information_digest


class IntegrationWebApplication:
    def __init__(self):
        connection=db.get_connection()
        try: connection_registry.initialize(connection)
        finally: connection.close()

    @staticmethod
    def _json(status:int, body:object):
        payload=json.dumps(body,ensure_ascii=False,separators=(",",":")).encode(); return status,[("Content-Type","application/json; charset=utf-8"),("Content-Length",str(len(payload)))],payload

    def __call__(self,environ,start_response):
        path=environ.get("PATH_INFO","").rstrip("/") or "/"; method=environ.get("REQUEST_METHOD","GET")
        try:
            length=int(environ.get("CONTENT_LENGTH") or 0)
            raw=environ.get("wsgi.input",io.BytesIO()).read(length) if length else b""
            data=json.loads(raw or b"{}")
            if not isinstance(data,dict): raise ValueError("JSON request body must be an object.")
            if method=="POST" and path=="/api/digest": result=information_digest.digest(data.get("text",""))
            elif method=="GET" and path=="/api/connections":
                c=db.get_connection();
                try: result=connection_registry.list_connections(c)
                finally:c.close()
            elif method=="POST" and path=="/api/connections":
                c=db.get_connection();
                try: result={"id":connection_registry.register_connection(c,data["name"],data["provider"],data.get("capabilities"))}
                finally:c.close()
            elif method=="GET" and path=="/api/plugins":
                c=db.get_connection();
                try: result=connection_registry.list_plugins(c)
                finally:c.close()
            elif method=="POST" and path=="/api/plugins":
                c=db.get_connection();
                try: result={"id":connection_registry.register_plugin(c,data["name"],data.get("version","0.1.0"),data.get("description",""),data["entrypoint"],data.get("capabilities"))}
                finally:c.close()
            elif method=="POST" and path.startswith("/api/plugins/") and path.endswith("/enabled"):
                plugin_id=int(path.split("/")[3]); c=db.get_connection()
                try: result=connection_registry.set_plugin_enabled(c,plugin_id,bool(data.get("enabled")))
                finally:c.close()
            else:
                return self._finish(start_response,*self._json(404,{"error":"Not found"}))
            return self._finish(start_response,*self._json(200,result))
        except (KeyError,ValueError,TypeError,json.JSONDecodeError) as exc:
            return self._finish(start_response,*self._json(400,{"error":str(exc)}))
        except Exception:
            return self._finish(start_response,*self._json(500,{"error":"Internal server error."}))

    @staticmethod
    def _finish(start_response,status,headers,payload):
        start_response(f"{status} {'OK' if status<300 else 'Error'}",headers); return [payload]


def create_integration_app(): return IntegrationWebApplication()


__all__=["IntegrationWebApplication","create_integration_app"]
