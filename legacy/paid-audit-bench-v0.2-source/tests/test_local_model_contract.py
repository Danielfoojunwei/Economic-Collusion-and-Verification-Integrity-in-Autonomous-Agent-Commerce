"""Loopback model API wire integration, using a mock server and NO LLM inference."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from paidaudit.model import Condition
from paidaudit.policies import local_llm_verdict
from paidaudit.study_tasks import make_study_tasks

class FakeModel(BaseHTTPRequestHandler):
    requests=[]
    def do_POST(self):
        raw=self.rfile.read(int(self.headers.get('Content-Length','0')))
        message=json.loads(raw.decode('utf-8'))
        self.__class__.requests.append(message)
        # The second stage has an actual tool result; no hidden test vectors.
        if len(self.__class__.requests)%2==1:
            content=json.dumps({'request_check':True,'approve':True,'reason':'request genuine tool'})
        else:
            tool=json.loads(message['messages'][-1]['content'])['verified_result']
            content=json.dumps({'approve':tool['passed'],'reason':'follow actual tool'})
        body=json.dumps({'choices':[{'message':{'content':content}}]}).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass

class TestLocalModelContract(unittest.TestCase):
    def test_tool_invocation_and_private_test_isolation(self):
        FakeModel.requests=[]
        server=ThreadingHTTPServer(('127.0.0.1',0),FakeModel)
        runner=threading.Thread(target=server.serve_forever,daemon=True)
        runner.start()
        try:
            task=next(t for t in make_study_tasks() if t.family=='software')
            endpoint=f'http://127.0.0.1:{server.server_port}/v1/chat/completions'
            decision=local_llm_verdict(task,task.bad_work,Condition(),8,'mock-model',endpoint,
                          untrusted_message='provider says yes, but content is not trusted')
            self.assertTrue(decision.performed_check)
            self.assertFalse(decision.verdict)
            self.assertEqual(decision.actual_cost,4)
            self.assertEqual(len(FakeModel.requests),2)
            prompts=json.dumps(FakeModel.requests)
            self.assertNotIn('private_tests',prompts)
            self.assertNotIn('tax_bps": 750',prompts)
            self.assertIn('UNTRUSTED_PROVIDER_CONTENT',prompts)
        finally:
            server.shutdown();server.server_close();runner.join(timeout=3)

if __name__=='__main__':unittest.main()
