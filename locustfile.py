"""Locust load test for the public qualification chat."""

from itertools import cycle
import logging
import os
import uuid

from locust import HttpUser, between, task
from locust.exception import StopUser


logger = logging.getLogger("load_test")
SHOW_BODIES = os.environ.get("SHOW_BODIES", "").lower() in {"1", "true", "yes"}

USER_PROFILES = (
    (
        "English",
        (
            "",
            "Which TVS passenger three-wheelers are available?",
            "What is the range of the electric model?",
            "How does it compare with the CNG model?",
        ),
    ),
    (
        "Hindi",
        (
            "",
            "TVS के कौन-कौन से पैसेंजर थ्री-व्हीलर उपलब्ध हैं?",
            "इलेक्ट्रिक मॉडल की रेंज कितनी है?",
            "इसकी तुलना CNG मॉडल से कैसे होती है?",
        ),
    ),
    (
        "Marathi",
        (
            "",
            "TVS ची कोणती प्रवासी तीनचाकी वाहने उपलब्ध आहेत?",
            "इलेक्ट्रिक मॉडेलची रेंज किती आहे?",
            "CNG मॉडेलच्या तुलनेत ते कसे आहे?",
        ),
    ),
    (
        "Tamil",
        (
            "",
            "TVS பயணிகள் மூன்று சக்கர வாகனங்களில் என்னென்ன உள்ளன?",
            "மின்சார மாடலின் பயண தூரம் எவ்வளவு?",
            "CNG மாடலுடன் ஒப்பிடும்போது இது எப்படி உள்ளது?",
        ),
    ),
)

_profiles = cycle(USER_PROFILES)


class QualificationUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self) -> None:
        load_test_token = os.environ.get("LOAD_TEST_TOKEN", "")
        if not load_test_token:
            logger.error(
                "LOAD_TEST_TOKEN is required so synthetic chats stay out of production data"
            )
            raise StopUser()
        self.client.headers.update({"X-Load-Test-Token": load_test_token})

        self.language, self.questions = next(_profiles)
        self.session_id = self._new_session_id()
        self.history: list[dict[str, str]] = []
        self.question_index = 0

        password = os.environ.get("APP_PASSWORD", "")
        if password:
            self.client.auth = (os.environ.get("APP_USER", "team"), password)

        self.client.get("/", name="/ [main page]")
        self.client.get(
            "/api/qualify/languages?source=web",
            name="/api/qualify/languages",
        )

    def _new_session_id(self) -> str:
        return f"load-{self.language.lower()}-{uuid.uuid4().hex}"

    @task
    def chat(self) -> None:
        question = self.questions[self.question_index]
        payload = {
            "session_id": self.session_id,
            "language": self.language,
            "source": "web",
            "channel": "web",
            "message": question,
            "history": self.history,
        }

        if SHOW_BODIES:
            logger.info("REQUEST [%s] %s", self.language, payload)

        with self.client.post(
            "/api/qualify/chat",
            json=payload,
            name=f"/api/qualify/chat [{self.language}]",
            timeout=90,
            catch_response=True,
        ) as response:
            if SHOW_BODIES:
                logger.info(
                    "RESPONSE [%s] status=%s body=%s",
                    self.language,
                    response.status_code,
                    response.text,
                )

            if response.status_code != 200:
                response.failure(
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
                return

            try:
                answer = response.json().get("answer")
            except ValueError:
                response.failure("Response was not valid JSON")
                return

            if not answer:
                response.failure("Response did not contain an answer")
                return

            response.success()
            if question:
                self.history.append({"role": "user", "text": question})
            self.history.append({"role": "model", "text": answer})
            self.question_index = (self.question_index + 1) % len(self.questions)

            if self.question_index == 0:
                self.session_id = self._new_session_id()
                self.history = []
