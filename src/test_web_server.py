import io
import json
import os
import tempfile
import unittest
from typing import cast

import db
from web_api import create_app
from web_server import create_site_app
from workspace_application import WorkspaceApplication


class TestSiteApplication(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.old=db.DATABASE_PATH; db.DATABASE_PATH=os.path.join(self.temp.name,"site.db")
        self.workspace=WorkspaceApplication(os.path.join(self.temp.name,"storage")); self.api=create_app(self.workspace); self.project_id=self.workspace.create_project("Site Project")
        self.site=create_site_app(self.api,os.path.join(os.path.dirname(__file__),"..","web"))
    def tearDown(self): db.DATABASE_PATH=self.old; self.temp.cleanup()
    def call(self,path,method="GET",payload=None):
        captured:dict[str,object]={}; body=json.dumps(payload).encode() if payload is not None else b""
        def start_response(status,headers): captured["status"],captured["headers"]=status,dict(headers)
        environ={"REQUEST_METHOD":method,"PATH_INFO":path,"QUERY_STRING":"","CONTENT_LENGTH":str(len(body)),"wsgi.input":io.BytesIO(body)}
        raw=b"".join(self.site(environ,start_response)); parsed:object=None
        if raw and "application/json" in cast(dict[str,str],captured.get("headers",{})).get("Content-Type",""): parsed=json.loads(raw)
        return captured,raw,parsed
    def test_serves_interactive_client_assets(self):
        for path,content_type in (("/","text/html"),("/app.js","text/javascript"),("/interaction-fixes.js","text/javascript"),("/beta-features.js","text/javascript"),("/styles.css","text/css")):
            response,body,_=self.call(path); self.assertEqual(response["status"],"200 OK"); self.assertIn(content_type,cast(dict[str,str],response["headers"])["Content-Type"]); self.assertGreater(len(body),100)
        _,index,_=self.call("/"); text=index.decode(); self.assertIn("/app.js",text); self.assertIn("/interaction-fixes.js",text); self.assertIn("/beta-features.js",text)
    def test_delegates_api_routes(self):
        response,_,payload=self.call("/api/health"); self.assertEqual(response["status"],"200 OK"); self.assertEqual(payload,{"status":"ok"})
    def test_delegates_engineering_routes(self):
        response,_,payload=self.call(f"/api/engineering/projects/{self.project_id}/requirements"); self.assertEqual(response["status"],"200 OK"); self.assertEqual(payload,[])
    def test_delegates_integration_routes(self):
        response,_,payload=self.call("/api/digest","POST",{"text":"Pressure is 10 MPa. The value may vary."}); self.assertEqual(response["status"],"200 OK"); digest=cast(dict[str,object],payload); statistics=cast(dict[str,object],digest["statistics"]); self.assertEqual(statistics["sentences"],2)
        response,_,payload=self.call("/api/connections"); self.assertEqual((response["status"],payload),("200 OK",[]))
    def test_delegates_major_calculation_navigation(self):
        response,_,payload=self.call("/api/calculations/majors"); self.assertEqual(response["status"],"200 OK"); majors=cast(list[dict[str,object]],payload); names={str(item["name"]) for item in majors}; self.assertEqual(len(names),6); self.assertIn("Energy & Earth Resources Engineering", names); energy=next(item for item in majors if item["name"]=="Energy & Earth Resources Engineering"); includes=cast(tuple[str,...],energy["includes"]); calculations=cast(tuple[str,...],energy["calculations"]); self.assertIn("Petroleum Engineering", includes); self.assertTrue(calculations)
        response,_,detail=self.call("/api/calculations/majors/Energy%20%26%20Earth%20Resources%20Engineering"); self.assertEqual(response["status"],"200 OK"); detail_dict=cast(dict[str,object],detail); self.assertEqual(detail_dict["name"],"Energy & Earth Resources Engineering")
    def test_rejects_path_traversal(self): response,_,_=self.call("/../README.md"); self.assertEqual(response["status"],"404 Error")


if __name__=="__main__": unittest.main()
