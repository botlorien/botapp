# using ubuntu LTS version
FROM ubuntu:latest AS builder-image

# avoid stuck build due to user prompt
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install --no-install-recommends -y tzdata \
    python3 python3-pip python3-venv python3-tk python3-wheel \
    git wget firefox  build-essential && \
    wget -nc https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt-get install -f -y ./google-chrome-stable_current_amd64.deb && \
	apt-get clean && rm -rf /var/lib/apt/lists/*

RUN ln -fs /usr/share/zoneinfo/America/Cuiaba /etc/localtime
RUN echo "America/Cuiaba" > /etc/timezone

RUN python3 -m venv /home/myuser/venv
ENV PATH="/home/myuser/venv/bin:$PATH"

# install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir wheel
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir --upgrade -r requirements.txt


FROM ubuntu:latest AS runner-image
RUN apt-get update && apt-get install --no-install-recommends -y python3 python3-venv python3-tk wget firefox tzdata&& \
    wget -nc https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt-get install -f -y ./google-chrome-stable_current_amd64.deb && \
	apt-get clean && rm -rf /var/lib/apt/lists/*

RUN ln -fs /usr/share/zoneinfo/America/Cuiaba /etc/localtime
RUN echo "America/Cuiaba" > /etc/timezone

RUN useradd --create-home myuser
COPY --from=builder-image /home/myuser/venv /home/myuser/venv



RUN mkdir /home/myuser/code
WORKDIR /home/myuser/code
COPY . .

RUN chmod +x ./entrypoint.sh
RUN chown -R myuser:myuser /home/myuser/code

USER myuser

ENV PYTHONUNBUFFERED=1
ENV VIRTUAL_ENV=/home/myuser/venv
ENV PATH="/home/myuser/venv/bin:$PATH"

CMD ["./entrypoint.sh"]

