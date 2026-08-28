const dialog = document.getElementById("lesson-details-dialog");
const closeButton = dialog.querySelector(".lesson-details-close");
const fields = {
    title: document.getElementById("lesson-details-title"),
    time: document.getElementById("lesson-details-time"),
    room: document.getElementById("lesson-details-room"),
    teacher: document.getElementById("lesson-details-teacher"),
    info: document.getElementById("lesson-details-info"),
    studentInfo: document.getElementById("lesson-details-student-info"),
    substitutionText: document.getElementById("lesson-details-substitution-text")
};
const rows = {
    info: document.getElementById("lesson-details-info-row"),
    studentInfo: document.getElementById("lesson-details-student-info-row"),
    substitutionText: document.getElementById("lesson-details-substitution-text-row")
};
const timetableLayout = document.querySelector(".timetable-layout");
timetableLayout.style.setProperty("--slot-count", timetableLayout.dataset.slotCount);

function showLessonDetails(card) {
    const lesson = JSON.parse(card.dataset.lesson);
    fields.title.textContent = lesson.subject;
    fields.time.textContent = `${lesson.start}-${lesson.end} Uhr`;
    fields.room.textContent = lesson.room || "Kein Raum";
    fields.teacher.textContent = lesson.teacher || "Kein Lehrer";
    fields.info.textContent = lesson.full_info || "Keine Unterrichtsinformation";
    fields.studentInfo.textContent = lesson.student_info || "Keine Stundenplan-Info";
    fields.substitutionText.textContent = lesson.substitution?.full_text || "Keine Vertretung";
    rows.info.hidden = !lesson.full_info;
    rows.studentInfo.hidden = !lesson.student_info;
    rows.substitutionText.hidden = !lesson.substitution?.full_text;
    dialog.showModal();
}

document.querySelectorAll(".timetable-card").forEach((card) => {
    card.addEventListener("click", () => showLessonDetails(card));
});

closeButton.addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
        dialog.close();
    }
});
