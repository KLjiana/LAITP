@echo off
echo {"protocol_version":"1.0","request_id":"req-sup-slow","project_id":"proj-sup","task_id":"task-sup-slow","message_type":"progress","sequence":0,"artifact_id":null,"payload":{"stage":"load","completed":0,"total":1}}
ping -n 20 127.0.0.1 > nul
echo {"protocol_version":"1.0","request_id":"req-sup-slow","project_id":"proj-sup","task_id":"task-sup-slow","message_type":"result","sequence":1,"artifact_id":"art-slow","payload":{"operation":"validate","artifact":{"artifact_id":"art-slow","manifest_path":"manifest.json","manifest_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}}
exit /b 0
