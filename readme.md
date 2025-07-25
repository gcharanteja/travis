start the applicaition with the virtual environment

.\venv\Scripts\activate

run the command in the env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

to export

mkdir -p app/{api/v1,config,core,models,schemas,services,utils} docs scripts tests uploads/avatars && touch .env .env.example .gitignore coreMIDDLEWARE.md docker-compose.yml Dockerfile flow.md main.py readme.md requirements.txt app/api/{deps.py,**init**.py} app/api/v1/{accounts.py,ai_coach.py,auth.py,goals.py,investments.py,portfolios.py,transactions.py,users.py,**init**.py} app/config/{database.py,settings.py,**init**.py} app/core/{exceptions.py,middleware.py,security.py,**init**.py} app/models/{account.py,chat.py,goal.py,portfolio.py,transaction.py,user.py,**init**.py} app/schemas/{account.py,chat.py,goal.py,portfolio.py,transaction.py,user.py,**init**.py} app/services/{ai_service.py,analytics_service.py,auth_service.py,investment_service.py,mock_bank_service.py,notification_service.py,plaid_service.py,**init**.py} app/utils/{helpers.py,validators.py,**init**.py} app/{main.py,**init**.py} docs/{account.md,ai_coach.md,auth.md,authuser.md,goals.md,investemnts.md,portfolio.md,transactions.md} scripts/nalladb.py tests/{conftest.py,test_accounts.py,test_ai_coach.py,test_auth.py,test_auth_and_profile.py,**init**.py} uploads/avatars/{6852928936b898edd7f7bda6_f3ce6549-090f-42fc-8310-4f30be0e106f.jpg,6852a8097dc3f22307e1ddd9_473c05c0-713a-471a-b7ce-a715e2f9d614.png,6852a8097dc3f22307e1ddd9_70494ae6-a892-423d-8a65-ee7d669958f7.png,6852a8097dc3f22307e1ddd9_eadb652d-cada-4940-a955-e5c47b972c2e.png,6852a8097dc3f22307e1ddd9_f0a3ef5e-cbd0-4ca2-9c7a-342c8f6f59d9.png,6852a8097dc3f22307e1ddd9_f6ac3571-8e91-4cd7-a5bb-ee64c16adf4a.png,6863a88ca4c3b24b9e1e835f_597f79fd-c678-427b-83a3-f00e05e15036.jpg}

annotated-types==0.7.0
anyio==4.9.0
astropy==7.1.0
astropy-iers-data==0.2025.6.23.0.39.50
bcrypt==4.3.0
certifi==2025.6.15
charset-normalizer==3.4.2
click==8.2.1
colorama==0.4.6
contourpy==1.3.2
cycler==0.12.1
distro==1.9.0
dnspython==2.7.0
email_validator==2.2.0
fastapi==0.115.12
fonttools==4.58.4
h11==0.16.0
httpcore==1.0.9
httpx==0.28.1
idna==3.10
iniconfig==2.1.0
jiter==0.10.0
kiwisolver==1.4.8
logger==1.4
matplotlib==3.10.3
motor==3.7.1
networkx==3.5
nulltype==2.3.1
numpy==2.3.0
openai==1.93.0
packaging==25.0
pandas==2.3.0
passlib==1.7.4
phonenumbers==9.0.7
pillow==11.2.1
plaid-python==34.0.0
pluggy==1.6.0
pydantic==2.11.5
pydantic-settings==2.9.1
pydantic_core==2.33.2
pyerfa==2.0.1.5
Pygments==2.19.2
PyJWT==2.10.1
pymongo==4.13.0
pyparsing==3.2.3
pytest==8.4.1
python-dateutil==2.9.0.post0
python-dotenv==1.1.0
python-multipart==0.0.20
pytz==2025.2
PyYAML==6.0.2
requests==2.32.4
scipy==1.16.0
six==1.17.0
sniffio==1.3.1
starlette==0.46.2
tqdm==4.67.1
typing-inspection==0.4.1
typing_extensions==4.14.0
tzdata==2025.2
urllib3==2.4.0
uvicorn==0.34.3
