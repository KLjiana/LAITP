@echo off
echo {"protocol_version":"1.0","request_id":"req-sup-ok","project_id":"proj-sup","task_id":"task-sup-ok","message_type":"progress","sequence":0,"artifact_id":null,"payload":{"stage":"load","completed":0,"total":1}}
echo {"protocol_version":"1.0","request_id":"req-sup-ok","project_id":"proj-sup","task_id":"task-sup-ok","message_type":"result","sequence":1,"artifact_id":"art-sup","payload":{"operation":"validate","artifact":{"artifact_id":"art-sup","manifest_path":"manifest.json","manifest_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}}
exit /b 0
