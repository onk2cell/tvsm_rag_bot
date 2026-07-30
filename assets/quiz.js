/**
 * Minimal quiz widget. Markup:
 * <div class="quiz" data-answer="1">
 *   <h3>Question?</h3>
 *   <div class="options">
 *     <button type="button" class="option" data-choice="0">...</button>
 *     ...
 *   </div>
 *   <p class="feedback" hidden></p>
 * </div>
 */
(function () {
  function initQuiz(root) {
    const answer = String(root.dataset.answer);
    const feedback = root.querySelector(".feedback");
    const buttons = [...root.querySelectorAll("button.option")];
    const explainOk = root.dataset.ok || "Correct.";
    const explainBad = root.dataset.bad || "Not quite — try again, or ask your teacher.";

    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const choice = String(btn.dataset.choice);
        const correct = choice === answer;
        buttons.forEach((b) => {
          b.disabled = true;
          if (String(b.dataset.choice) === answer) b.classList.add("correct");
        });
        if (!correct) btn.classList.add("wrong");
        if (feedback) {
          feedback.hidden = false;
          feedback.textContent = correct ? explainOk : explainBad;
          feedback.classList.toggle("ok", correct);
          feedback.classList.toggle("bad", !correct);
        }
      });
    });
  }

  document.querySelectorAll(".quiz[data-answer]").forEach(initQuiz);
})();
