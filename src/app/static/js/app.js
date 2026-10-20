// DocuMind AI - frontend for the local RAG flow.
// All user-facing text is in Spanish; requests talk only to the local API.

(function () {
    "use strict";

    const state = {
        documents: [],
        selectedDocumentId: null,
        file: null,
    };

    const elements = {
        servicesStatus: document.getElementById("services-status"),
        pdfUpload: document.getElementById("pdf-upload"),
        uploadLabelText: document.getElementById("upload-label-text"),
        indexButton: document.getElementById("index-button"),
        uploadStatus: document.getElementById("upload-status"),
        documentsList: document.getElementById("documents-list"),
        questionInput: document.getElementById("question-input"),
        askButton: document.getElementById("ask-button"),
        answersContainer: document.getElementById("answers-container"),
    };

    function setMessage(element, text, kind) {
        element.textContent = text || "";
        element.className = "status-message" + (kind ? " " + kind : "");
    }

    function createStatusItem(text, kind) {
        const item = document.createElement("li");
        item.className = "status-item status-" + kind;
        const dot = document.createElement("span");
        dot.className = "status-dot";
        item.appendChild(dot);
        item.appendChild(document.createTextNode(text));
        return item;
    }

    async function fetchJson(url, options) {
        const response = await fetch(url, options);
        let body = null;
        try {
            body = await response.json();
        } catch (error) {
            body = null;
        }
        if (!response.ok) {
            const detail = body && body.detail ? body.detail : "Error " + response.status;
            throw new Error(detail);
        }
        return body;
    }

    function formatError(error) {
        if (error instanceof TypeError) {
            return "No se pudo contactar con el servidor local. Comprueba que la aplicación esté en ejecución.";
        }
        return error.message || "Ha ocurrido un error inesperado.";
    }

    // Service status -------------------------------------------------------

    async function loadServicesStatus() {
        elements.servicesStatus.innerHTML = "";
        try {
            const status = await fetchJson("/api/services/status");
            elements.servicesStatus.appendChild(
                createStatusItem(
                    status.ollama_available
                        ? "Ollama disponible"
                        : "Ollama no disponible (inicia el servicio local)",
                    status.ollama_available ? "ok" : "error"
                )
            );
            elements.servicesStatus.appendChild(
                createStatusItem(
                    "Modelo de respuestas (" + status.ollama_llm_model_present + ")",
                    status.ollama_llm_model_present ? "ok" : "warn"
                )
            );
            elements.servicesStatus.appendChild(
                createStatusItem(
                    "Modelo de embeddings",
                    status.ollama_embedding_model_present ? "ok" : "warn"
                )
            );
            elements.servicesStatus.appendChild(
                createStatusItem(
                    status.database_available
                        ? "Base de datos PostgreSQL disponible"
                        : "Base de datos PostgreSQL no disponible",
                    status.database_available ? "ok" : "error"
                )
            );
            elements.servicesStatus.appendChild(
                createStatusItem(
                    status.embedding_dimension_configured
                        ? "Dimensión de embeddings configurada"
                        : "Falta configurar EMBEDDING_DIMENSION",
                    status.embedding_dimension_configured ? "ok" : "warn"
                )
            );
        } catch (error) {
            elements.servicesStatus.appendChild(createStatusItem(formatError(error), "error"));
        }
    }

    // Documents ------------------------------------------------------------

    function renderDocuments() {
        elements.documentsList.innerHTML = "";
        if (state.documents.length === 0) {
            const empty = document.createElement("li");
            empty.className = "empty-state";
            empty.textContent = "Todavía no hay documentos indexados.";
            elements.documentsList.appendChild(empty);
            return;
        }

        state.documents.forEach(function (doc) {
            const item = document.createElement("li");
            item.className = "document-item";
            if (doc.id === state.selectedDocumentId) {
                item.classList.add("selected");
            }

            const radio = document.createElement("input");
            radio.type = "radio";
            radio.name = "document";
            radio.value = doc.id;
            radio.checked = doc.id === state.selectedDocumentId;
            radio.addEventListener("change", function () {
                state.selectedDocumentId = doc.id;
                renderDocuments();
            });

            const meta = document.createElement("div");
            meta.className = "document-meta";

            const name = document.createElement("span");
            name.className = "document-name";
            name.textContent = doc.name;

            const detail = document.createElement("span");
            detail.className = "document-detail";
            detail.textContent =
                doc.page_count +
                (doc.page_count === 1 ? " página" : " páginas") +
                " · " +
                doc.chunk_count +
                (doc.chunk_count === 1 ? " fragmento" : " fragmentos");

            meta.appendChild(name);
            meta.appendChild(detail);

            item.appendChild(radio);
            item.appendChild(meta);
            item.addEventListener("click", function (event) {
                if (event.target !== radio) {
                    radio.checked = true;
                    state.selectedDocumentId = doc.id;
                    renderDocuments();
                }
            });

            elements.documentsList.appendChild(item);
        });
    }

    async function loadDocuments() {
        try {
            const data = await fetchJson("/api/documents");
            state.documents = data.documents || [];
            if (state.documents.length > 0 && !state.selectedDocumentId) {
                state.selectedDocumentId = state.documents[0].id;
            }
            if (
                state.selectedDocumentId &&
                !state.documents.some(function (doc) {
                    return doc.id === state.selectedDocumentId;
                })
            ) {
                state.selectedDocumentId = state.documents.length ? state.documents[0].id : null;
            }
            renderDocuments();
        } catch (error) {
            elements.documentsList.innerHTML = "";
            const item = document.createElement("li");
            item.className = "empty-state";
            item.textContent = formatError(error);
            elements.documentsList.appendChild(item);
        }
    }

    // Indexing -------------------------------------------------------------

    async function indexDocument() {
        if (!state.file) {
            setMessage(elements.uploadStatus, "Selecciona primero un archivo PDF.", "error");
            return;
        }

        elements.indexButton.disabled = true;
        setMessage(elements.uploadStatus, "Indexando el documento. Puede tardar unos minutos...", "info");

        const formData = new FormData();
        formData.append("file", state.file);

        try {
            const result = await fetchJson("/api/documents/index", {
                method: "POST",
                body: formData,
            });
            const doc = result.document;
            setMessage(
                elements.uploadStatus,
                (result.already_indexed ? "Documento ya conocido, reindexado: " : "Documento indexado: ") +
                    doc.name +
                    " (" +
                    result.chunk_count +
                    " fragmentos)",
                "ok"
            );
            state.selectedDocumentId = doc.id;
            await loadDocuments();
        } catch (error) {
            setMessage(elements.uploadStatus, formatError(error), "error");
        } finally {
            elements.indexButton.disabled = false;
        }
    }

    // Question answering ---------------------------------------------------

    function renderAnswer(response) {
        elements.answersContainer.innerHTML = "";

        const wrapper = document.createElement("div");
        wrapper.className = response.grounded ? "answer-grounded" : "answer-abstained";

        const text = document.createElement("p");
        text.className = "answer-text";
        text.textContent = response.answer;
        wrapper.appendChild(text);

        if (response.abstained) {
            const caveat = document.createElement("p");
            caveat.className = "answer-caveat";
            caveat.textContent =
                "Abstención: no hay evidencia suficiente en los fragmentos recuperados para responder con fundamento.";
            wrapper.appendChild(caveat);
        } else {
            const caveat = document.createElement("p");
            caveat.className = "answer-caveat";
            caveat.textContent =
                "Respuesta generada por un modelo local a partir de las fuentes citadas. Verifica siempre las citas.";
            wrapper.appendChild(caveat);
        }

        if (response.citations && response.citations.length > 0) {
            const list = document.createElement("ul");
            list.className = "citations";
            response.citations.forEach(function (citation) {
                const item = document.createElement("li");
                item.className = "citation";

                const header = document.createElement("div");
                header.className = "citation-header";
                header.textContent =
                    "Página " + citation.page_number + " · similitud " + citation.score.toFixed(3);

                const excerpt = document.createElement("div");
                excerpt.className = "citation-excerpt";
                excerpt.textContent = citation.excerpt;

                item.appendChild(header);
                item.appendChild(excerpt);
                list.appendChild(item);
            });
            wrapper.appendChild(list);
        }

        elements.answersContainer.appendChild(wrapper);
    }

    async function askQuestion() {
        const question = elements.questionInput.value.trim();
        if (!question) {
            elements.answersContainer.innerHTML =
                '<p class="empty-state">Escribe una pregunta antes de enviarla.</p>';
            return;
        }

        elements.askButton.disabled = true;
        elements.answersContainer.innerHTML =
            '<p class="empty-state">Buscando evidencia y generando la respuesta...</p>';

        const payload = { question: question };
        if (state.selectedDocumentId) {
            payload.document_ids = [state.selectedDocumentId];
        }

        try {
            const response = await fetchJson("/api/documents/ask", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            renderAnswer(response);
        } catch (error) {
            elements.answersContainer.innerHTML = "";
            const paragraph = document.createElement("p");
            paragraph.className = "empty-state";
            paragraph.textContent = formatError(error);
            elements.answersContainer.appendChild(paragraph);
        } finally {
            elements.askButton.disabled = false;
        }
    }

    // Wiring ---------------------------------------------------------------

    document.addEventListener("DOMContentLoaded", function () {
        elements.pdfUpload.addEventListener("change", function () {
            state.file = this.files && this.files[0] ? this.files[0] : null;
            elements.uploadLabelText.textContent = state.file
                ? state.file.name
                : "Seleccionar un archivo PDF";
            setMessage(elements.uploadStatus, "", "");
        });

        elements.indexButton.addEventListener("click", indexDocument);
        elements.askButton.addEventListener("click", askQuestion);

        elements.questionInput.addEventListener("keydown", function (event) {
            if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                askQuestion();
            }
        });

        loadServicesStatus();
        loadDocuments();
    });
})();
