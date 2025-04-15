FROM python:3.12.2

WORKDIR /code

COPY ./test_requirements.txt /code/test_requirements.txt

RUN pip install --no-cache-dir --upgrade -r /code/test_requirements.txt

COPY . .

CMD ["gunicorn","-b", "0.0.0.0:7860", "test:app"]
