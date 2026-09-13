import json
import os
import tempfile
import unittest

import db
from web_api import create_app
from workspace_application import WorkspaceApplication


class TestAuthHttpProbe(unittest.TestCase):
    def test_probe(self):
        temp=tempfile.TemporaryDirectory(); old=db.DATABASE_PATH; db.DATABASE_PATH=os.path.join(temp.name,'auth.db')
        try:
            workspace=WorkspaceApplication(os.path.join(temp.name,'storage')); app=create_app(workspace)
            status,headers,raw=app.request('POST','/api/auth/signup',json.dumps({'email':'riley@example.com','password':'safe-pass-123','display_name':'Riley'}).encode())
            self.assertEqual(status,201,f'status={status} body={raw.decode()} headers={headers}')
        finally:
            db.DATABASE_PATH=old; temp.cleanup()
