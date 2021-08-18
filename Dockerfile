FROM python:3.9.6-slim

RUN pip install pipenv
RUN apt-get update && apt-get install -y git

WORKDIR /discord-modlinkbot

COPY Pipfile Pipfile.lock ./
RUN pipenv install --deploy --ignore-pipfile

COPY . .

CMD [ "pipenv", "run", "bot" ]