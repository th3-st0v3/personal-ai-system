import json
import os
import tempfile
import unittest
from typing import cast

import db
import engineering_modeler
import information_digest
from auth_service import initialize as initialize_auth
from auth_service import login, signup
from connection_registry import initialize as initialize_connections
from connection_registry import list_connections, list_plugins, register_connection, register_plugin, set_plugin_enabled
from chat_service import initialize as initialize_chat
from simulation_library import run_simulation


class TestBetaServices(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=db.DATABASE_PATH
        db.DATABASE_PATH=os.path.join(self.temp.name,"beta.db")
        c=db.get_connection()
        initialize_auth(c); initialize_chat(c); initialize_connections(c); c.close()
    def tearDown(self):
        db.DATABASE_PATH=self.old
        self.temp.cleanup()

    def test_auth_password_and_session(self):
        c=db.get_connection()
        user=signup(c,"person@example.com","long-password","Person")
        token,logged=login(c,"person@example.com","long-password")
        self.assertEqual(user["email"],logged["email"])
        self.assertTrue(token)
        c.close()

    def test_simulation_returns_trace_sections(self):
        result=run_simulation("wellbore_hydraulics",{"depth":1000,"density":1000,"diameter":0.1,"velocity":1,"viscosity":0.001})
        outputs=cast(dict[str, object], result["outputs"])
        self.assertGreater(cast(float, outputs["bottom_pressure"]),0)
        self.assertTrue(result["steps"] and result["assumptions"] and result["limitations"])

    def test_auto_modeler_finds_petroleum_tools(self):
        plan=engineering_modeler.build_model_plan("Model wellbore pressure and velocity for a drilling problem")
        self.assertEqual(plan["discipline"],"petroleum engineering")
        calculations=cast(list[object], plan["calculations"])
        simulations=cast(list[object], plan["simulations"])
        self.assertTrue(calculations or simulations)

    def test_digest_separates_qualified_statements(self):
        result=information_digest.digest("Pressure is 10 MPa. The value may vary with temperature. Verify the source.")
        statistics=cast(dict[str, object], result["statistics"])
        uncertain=cast(list[object], result["uncertain_or_qualified"])
        self.assertEqual(statistics["sentences"],3)
        self.assertEqual(len(uncertain),1)
        self.assertTrue(result["open_questions"])

    def test_connection_and_plugin_registry(self):
        c=db.get_connection()
        connection_id=register_connection(c,"OpenRouter","openrouter",["chat","tools"])
        plugin_id=register_plugin(c,"engineering-tools","0.1.0","Engineering tool host","plugins.engineering",["calculations","simulations"])
        self.assertEqual(list_connections(c)[0]["id"],connection_id)
        enabled=set_plugin_enabled(c,plugin_id,True)
        self.assertTrue(enabled["enabled"])
        capabilities=cast(list[object], list_plugins(c)[0]["capabilities"])
        self.assertEqual(capabilities,["calculations","simulations"])
        c.close()


if __name__=="__main__": unittest.main()
