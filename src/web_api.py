"""Small, replaceable HTTP boundary over the stable application services."""
from __future__ import annotations

import base64
import json
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

import auth_service
import chat_service
import db
import ingestion_service
import policy
import project_service
import simulation_library
import workspace_browser
from calculation_application import CalculationApplication
from workspace_application import WorkspaceApplication


class WebApplication:
    """Serve JSON API resources without coupling HTTP handlers to storage."""

    MAX_REQUEST_BODY_BYTES = 8 * 1024 * 1024
    _ITEM_KINDS = frozenset(("folder", "note", "file"))
    ITEM_KINDS = ("folder", "note", "file")

    def __init__(self, workspace: WorkspaceApplication, calculations: CalculationApplication | None = None):
        self.workspace = workspace
        self.calculations = calculations or CalculationApplication()
        connection = db.get_connection()
        try:
            auth_service.initialize(connection)
            chat_service.initialize(connection)
            policy.initialize(connection)
        finally:
            connection.close()

    @staticmethod
    def _json(status: int, body: object, extra_headers: list[tuple[str, str]] | None = None) -> tuple[int, list[tuple[str, str]], bytes]:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        headers = [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))]
        if extra_headers: headers.extend(extra_headers)
        return status, headers, payload

    @staticmethod
    def _item(item) -> dict[str, object]:
        return {"kind": item.kind, "id": item.id, "project_id": item.project_id, "parent_id": item.parent_id, "name": item.name, "mime_type": item.mime_type, "content": item.content, "size_bytes": item.size_bytes, "created_at": item.created_at, "updated_at": item.updated_at, "metadata": item.metadata}

    @staticmethod
    def _session_token(environ: dict[str, object] | None = None, headers: dict[str, str] | None = None) -> str | None:
        raw=(environ or {}).get("HTTP_COOKIE") if environ is not None else (headers or {}).get("Cookie")
        if not raw:return None
        cookie=SimpleCookie();cookie.load(str(raw));return cookie["pas_session"].value if "pas_session" in cookie else None

    def _current_user(self, token: str | None) -> dict[str, object] | None:
        connection=db.get_connection()
        try:return auth_service.current_user(connection,token)
        finally:connection.close()

    def _manifest(self, user: dict[str, object] | None = None) -> dict[str, object]:
        categories=self.calculations.grouped_categories()
        return {"api_version":3,"user":user,"workspace":{"kinds":list(self.ITEM_KINDS),"sort_options":["none",*workspace_browser.SORT_OPTIONS.keys()],"context_actions":{kind:list(workspace_browser.get_context_actions(kind)) for kind in self.ITEM_KINDS},"multi_selection_actions":["open","copy","move","archive","invalidate","delete","properties"]},"calculations":{"categories":list(categories),"count":len(self.calculations.list_models())},"simulations":[{"key":s.key,"name":s.name,"discipline":s.discipline,"description":s.description,"parameters":list(s.parameters)} for s in simulation_library.list_simulations()],"navigation":["Chat","Projects","Education","Simulations","Calculations","Connections"],"models":[{"key":key,"model":model} for key,model in chat_service.MODEL_PROFILES.items()],"settings":{"themes":["system","light","dark"],"memory":True,"connectors":True,"tool_activity":True}}

    def request(self, method: str, target: str, body: bytes = b"", environ: dict[str, object] | None = None) -> tuple[int, list[tuple[str, str]], bytes]:
        try:
            if len(body)>self.MAX_REQUEST_BODY_BYTES:raise ValueError(f"Request body exceeds {self.MAX_REQUEST_BODY_BYTES} bytes.")
            parsed=urlsplit(target);path=parsed.path.rstrip("/") or "/";query={key:values[-1] for key,values in parse_qs(parsed.query).items()};data=json.loads(body or b"{}")
            if not isinstance(data,dict):raise ValueError("JSON request body must be an object.")
            token=self._session_token(environ or {});user=self._current_user(token);actor_id=str(user["id"]) if user else "local"
            if method=="GET" and path=="/api/health":return self._json(200,{"status":"ok"})
            if method=="GET" and path=="/api/manifest":return self._json(200,self._manifest(user))
            if method=="POST" and path=="/api/auth/signup":
                connection=db.get_connection()
                try:auth_service.signup(connection,data["email"],data["password"],data.get("display_name"));session,user=auth_service.login(connection,data["email"],data["password"])
                finally:connection.close()
                return self._json(201,{"user":user},[("Set-Cookie",f"pas_session={session}; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000")])
            if method=="POST" and path=="/api/auth/login":
                connection=db.get_connection()
                try:session,user=auth_service.login(connection,data["email"],data["password"])
                finally:connection.close()
                return self._json(200,{"user":user},[("Set-Cookie",f"pas_session={session}; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000")])
            if method=="POST" and path=="/api/auth/logout":
                auth_service.logout(token);return self._json(200,{"logged_out":True},[("Set-Cookie","pas_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")])
            if method=="GET" and path=="/api/auth/me":return self._json(200,{"user":user})
            if method=="GET" and path=="/api/projects":return self._json(200,self.workspace.list_projects())
            if method=="POST" and path=="/api/projects":return self._json(201,{"id":self.workspace.create_project(data["name"],data.get("description"))})
            if method=="GET" and path=="/api/calculations/categories":return self._json(200,self.calculations.grouped_categories())
            if method=="GET" and path=="/api/calculations/catalog":return self._json(200,[item.__dict__ for item in self.calculations.list_catalog_items(query.get("category"))])
            if method=="POST" and path=="/api/calculations/run":return self._json(200,self.calculations.run_trace(data["model_key"],data.get("inputs",{})).to_dict())
            if method=="GET" and path.startswith("/api/calculations/"):
                key=path.rsplit("/",1)[-1];model=self.calculations.get_model(key);method_version=self.calculations.get_method(key);parameters=self.calculations.get_parameters(key);catalog=self.calculations.get_catalog_entry(key)
                return self._json(200,{"model":model.__dict__,"method":method_version.__dict__,"parameters":[parameter.__dict__ for parameter in parameters],"catalog":catalog.__dict__})
            if method=="GET" and path=="/api/simulations":return self._json(200,[{"key":s.key,"name":s.name,"discipline":s.discipline,"description":s.description,"parameters":list(s.parameters)} for s in simulation_library.list_simulations()])
            if method=="POST" and path=="/api/simulations/run":
                connection=db.get_connection()
                try:policy.require(connection,"local","run_simulation")
                finally:connection.close()
                return self._json(200,simulation_library.run_simulation(data["simulation_key"],data.get("inputs",{})))
            if method=="POST" and path=="/api/chats":
                connection=db.get_connection()
                try:chat_id=chat_service.create_chat(connection,data.get("project_id"),data.get("title","New chat"))
                finally:connection.close()
                return self._json(201,{"id":chat_id})
            if method=="GET" and path=="/api/chats":
                project_id=int(query["project_id"]) if query.get("project_id") else None;connection=db.get_connection()
                try:return self._json(200,chat_service.list_chats(connection,project_id))
                finally:connection.close()
            if path.startswith("/api/chats/") and path.count("/")==3:
                chat_id=int(path.rsplit("/",1)[-1]);connection=db.get_connection()
                try:
                    if method=="GET":return self._json(200,chat_service.get_chat(connection,chat_id))
                    if method=="PATCH":
                        if "title" in data:chat_service.rename_chat(connection,chat_id,data["title"])
                        if "pinned" in data:chat_service.set_pinned(connection,chat_id,bool(data["pinned"]))
                        if "project_id" in data:chat_service.move_chat(connection,chat_id,data.get("project_id"))
                        return self._json(200,chat_service.get_chat(connection,chat_id))
                    if method=="DELETE":chat_service.delete_chat(connection,chat_id);return self._json(200,{"deleted":True})
                finally:connection.close()
            if method=="POST" and path.startswith("/api/chats/") and path.endswith("/messages"):
                chat_id=int(path.split("/")[3]);connection=db.get_connection()
                try:return self._json(200,chat_service.respond(connection,chat_id,data["content"],model=data.get("model"),mode=data.get("mode","auto")))
                finally:connection.close()
            parts=path.split("/")
            if len(parts)>=4 and parts[1:3]==["api","projects"]:
                project_id=int(parts[3])
                if method=="GET" and len(parts)==4:
                    connection=db.get_connection()
                    try:return self._json(200,project_service.get_project(connection,project_id))
                    finally:connection.close()
                if method=="PATCH" and len(parts)==4:
                    connection=db.get_connection()
                    try:return self._json(200,project_service.update_project(connection,project_id,name=data.get("name"),description=data.get("description")))
                    finally:connection.close()
                if method=="DELETE" and len(parts)==4:
                    connection=db.get_connection()
                    try:project_service.delete_project(connection,project_id)
                    finally:connection.close()
                    return self._json(200,{"deleted":True})
                if method=="GET" and len(parts)==5 and parts[4]=="items":
                    folder_id=int(query["folder_id"]) if query.get("folder_id") else None;return self._json(200,[self._item(item) for item in self.workspace.list_children(project_id,folder_id,sort=query.get("sort","a_z"))])
                if method=="GET" and len(parts)==5 and parts[4]=="breadcrumbs":
                    kind=self._kind(query["kind"]);item_id=int(query["id"]);item=self.workspace._browser_item(kind,item_id)
                    if item.project_id!=project_id:raise ValueError("Item belongs to another project.")
                    return self._json(200,[{"kind":kind_name,"id":crumb_id,"name":name} for kind_name,crumb_id,name in self.workspace.get_breadcrumbs(kind,item_id)])
                if method=="GET" and len(parts)==5 and parts[4]=="search":return self._json(200,[self._item(item) for item in self.workspace.search_project(project_id,query["q"],recursive=query.get("recursive","true").casefold()!="false")])
                if method=="POST" and len(parts)==5 and parts[4]=="folders":return self._json(201,{"id":self.workspace.create_folder(project_id,data["name"],data.get("parent_folder_id"))})
                if method=="POST" and len(parts)==5 and parts[4]=="notes":return self._json(201,{"id":self.workspace.create_note(project_id,data["title"],data.get("content",""),data.get("folder_id"),data.get("metadata"))})
                if method=="PATCH" and len(parts)==5 and parts[4]=="notes":
                    note_id=int(data["id"]);self.workspace._require_project_item("note",note_id,project_id);return self._json(200,self._item(self.workspace.update_note(note_id,title=data.get("title"),content=data.get("content"),metadata=data.get("metadata"))))
                if method=="DELETE" and len(parts)==5 and parts[4]=="notes":self.workspace.delete_note(int(data["id"]),project_id=project_id);return self._json(200,{"deleted":True})
                if method=="GET" and len(parts)==5 and parts[4]=="notes":
                    note=self.workspace.get_note(int(query["id"]));
                    if note is None or note.project_id!=project_id:raise ValueError("Note not found in project.")
                    return self._json(200,self._item(note))
                if method=="POST" and len(parts)==5 and parts[4]=="sources":
                    connection=db.get_connection()
                    try:policy.require(connection,actor_id,"ingest_source");result=ingestion_service.ingest_text(connection,project_id,data["title"],data["content"],source_type=data.get("source_type","text"),version=data.get("version"),url=data.get("url"),chunk_chars=int(data.get("chunk_chars",ingestion_service.DEFAULT_CHUNK_CHARS)))
                    finally:connection.close()
                    return self._json(201,result)
                if method=="GET" and len(parts)==5 and parts[4]=="sources":
                    connection=db.get_connection()
                    try:return self._json(200,ingestion_service.search_chunks(connection,project_id,query["q"],int(query.get("limit","10"))))
                    finally:connection.close()
                if method=="POST" and len(parts)==5 and parts[4]=="files":
                    if "name" not in data or "data_base64" not in data:raise ValueError("File name and data_base64 are required.")
                    payload=base64.b64decode(data["data_base64"],validate=True);return self._json(201,{"id":self.workspace.create_file(project_id,data["name"],payload,data.get("mime_type"),data.get("folder_id"))})
                if method=="GET" and len(parts)==5 and parts[4]=="files":
                    file_id=int(query["id"]);record=self.workspace.get_file(file_id)
                    if record is None or record["project_id"]!=project_id:raise ValueError("File not found in project.")
                    return self._json(200,{"id":file_id,"name":record["name"],"mime_type":record["mime_type"],"folder_id":record["folder_id"],"size_bytes":record["size_bytes"],"data_base64":base64.b64encode(self.workspace.read_file(file_id,project_id=project_id)).decode("ascii")})
                if method=="PUT" and len(parts)==5 and parts[4]=="files":
                    file_id=int(data["id"]);self.workspace._require_project_item("file",file_id,project_id);payload=base64.b64decode(data["data_base64"],validate=True);file=self.workspace.replace_file(file_id,payload,data.get("mime_type"),project_id=project_id);return self._json(200,{"id":file["id"],"name":file["name"],"size_bytes":file["size_bytes"],"mime_type":file["mime_type"]})
                if method=="POST" and len(parts)==5 and parts[4]=="copy":
                    selection=[(self._kind(item["kind"]),int(item["id"])) for item in data.get("selection",[])];
                    if not selection:raise ValueError("Selection is required.")
                    self.workspace.copy_selection(project_id,selection);return self._json(200,{"copied":[{"kind":k,"id":i} for k,i in selection]})
                if method=="POST" and len(parts)==5 and parts[4]=="paste":
                    selection=[(self._kind(item["kind"]),int(item["id"])) for item in data.get("selection",[])];
                    if not selection:raise ValueError("Clipboard selection is required.")
                    return self._json(201,{"created":self.workspace.paste_selection(project_id,data.get("target_folder_id"),self.workspace.copy_selection(project_id,selection))})
                if method=="POST" and len(parts)==5 and parts[4]=="duplicate":
                    kind,item_id=self._kind(data["kind"]),int(data["id"]);self.workspace._require_project_item(kind,item_id,project_id);return self._json(201,{"id":self.workspace.duplicate_item(project_id,kind,item_id)})
                if method=="POST" and len(parts)==5 and parts[4]=="move":
                    kind,item_id=self._kind(data["kind"]),int(data["id"]);self.workspace._require_project_item(kind,item_id,project_id);self.workspace.move_item(kind,item_id,data.get("target_folder_id"),project_id=project_id);return self._json(200,{"moved":True})
                if method=="POST" and len(parts)==5 and parts[4]=="lifecycle":
                    kind,item_id=self._kind(data["kind"]),int(data["id"]);self.workspace._require_project_item(kind,item_id,project_id);status=data["status"]
                    if kind=="folder":self.workspace.set_folder_lifecycle(item_id,status,project_id=project_id)
                    elif kind=="file":self.workspace.set_file_lifecycle(item_id,status,project_id=project_id)
                    else:
                        note=self.workspace.get_note(item_id);metadata=dict(note.metadata if note else {});metadata["lifecycle_status"]=status;self.workspace.update_note(item_id,metadata=metadata)
                    return self._json(200,{"updated":True})
                if method=="POST" and len(parts)==5 and parts[4]=="rename":
                    kind,item_id=self._kind(data["kind"]),int(data["id"]);self.workspace._require_project_item(kind,item_id,project_id);self.workspace.rename_item(kind,item_id,data["name"],project_id=project_id);return self._json(200,{"renamed":True})
                if method=="POST" and len(parts)==5 and parts[4]=="delete":
                    selection=[(self._kind(item["kind"]),int(item["id"])) for item in data.get("selection",[])];
                    if not selection:selection=[(self._kind(data["kind"]),int(data["id"]))]
                    return self._json(200,{"deleted":self.workspace.delete_selection(project_id,selection)})
                if method=="GET" and len(parts)==5 and parts[4]=="properties":
                    kind,item_id=self._kind(query["kind"]),int(query["id"]);properties=self.workspace.get_item_properties(kind,item_id)
                    if properties["project_id"]!=project_id:raise ValueError("Item belongs to another project.")
                    properties.pop("sha256",None);return self._json(200,properties)
            return self._json(404,{"error":"Not found"})
        except PermissionError as exc:return self._json(403,{"error":str(exc) or "Permission denied"})
        except (KeyError,ValueError,TypeError,json.JSONDecodeError,UnicodeDecodeError,base64.binascii.Error) as exc:return self._json(400,{"error":str(exc) or "Invalid request"})
        except Exception as exc:return self._json(500,{"error":str(exc) or "Internal server error"})

    @classmethod
    def _kind(cls,value:str)->str:
        if value not in cls._ITEM_KINDS:raise ValueError(f"Unsupported item kind '{value}'.")
        return value

    def __call__(self,environ,start_response):
        try:
            length=int(environ.get("CONTENT_LENGTH") or 0)
            if length<0:raise ValueError("Content length cannot be negative.")
            if length>self.MAX_REQUEST_BODY_BYTES:status,headers,payload=self._json(413,{"error":"Request body too large."})
            else:
                body=environ["wsgi.input"].read(length) if length else b"";target=environ.get("PATH_INFO","/")
                if environ.get("QUERY_STRING"):target+="?"+environ["QUERY_STRING"]
                status,headers,payload=self.request(environ.get("REQUEST_METHOD","GET"),target,body,environ)
        except (TypeError,ValueError) as exc:status,headers,payload=self._json(400,{"error":str(exc) or "Invalid request"})
        reason="OK" if status<300 else "Error";start_response(f"{status} {reason}",headers);return [payload]


def create_app(workspace:WorkspaceApplication,calculations:CalculationApplication|None=None)->WebApplication:return WebApplication(workspace,calculations)

__all__=["WebApplication","create_app"]
