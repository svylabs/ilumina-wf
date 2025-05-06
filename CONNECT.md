gcloud app deploy
gcloud app logs tail -s default
gcloud app instances list
gcloud app versions stop --service default 20250503t164809
gcloud app instances ssh aef-default-20250503t205803-abcd --service=default --version=20250503t205803
sudo docker ps
sudo docker exec -it <container_id> /bin/bash
