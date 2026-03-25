# Codebase Bug Log

This log contains identified bugs, potential security vulnerabilities, and logical errors in the `intersection-counter` project, discovered through static analysis, test execution, and code review.

## 1. Security Vulnerabilities

### 1.1 SQL Injection in `patch_event`
- **File:** `backend/routers/review.py`
- **Line:** 115
- **Description:** The `patch_event` endpoint uses f-string interpolation to build an `UPDATE` statement with user-provided `updates` (column names) and `params`. While the column names themselves are controlled by code (lines 106, 109), the execution pattern `conn.execute(f"UPDATE ...", params)` in line 115 is risky if the structure ever changes. More importantly, SQLite's `execute` method expects parameters for *values*, not for identifiers or partial query strings.
- **Impact:** Potential for data corruption or unauthorized data modification if input validation is bypassed.
- **Reproduction:** Call `PATCH /api/projects/{id}/review/{event_id}` with specially crafted `movement` or `vehicle_class` if validation in lines 91-94 is missing or incomplete.

### 1.2 Cross-Site Scripting (XSS) in Frontend
- **Files:** Multiple files in `frontend/js/` (e.g., `projects.js`, `review.js`, `calibration.js`)
- **Description:** Extensive use of `.innerHTML` to render data received from the backend. While `escapeHtml` and `_escR` are used in some places, they are inconsistently applied.
- **Examples:**
    - `frontend/js/projects.js`: `p.name` is escaped in `deleteProject` (line 32) but NOT in the main project list display (line 31: `html += '<h3>' + p.name + '</h3>'`).
    - `frontend/js/review.js`: `ev.leg_label` is escaped in `_buildLegOptions` but might be missing in other parts of `_reviewRow`.
- **Impact:** Maliciously named projects or leg labels could execute arbitrary JavaScript in the user's browser.

## 2. Logical & Runtime Errors

### 2.1 Potential Race Condition in Project Deletion
- **File:** `backend/routers/projects.py`
- **Line:** 81
- **Description:** `shutil.rmtree(project_dir)` is called without checking if any background threads (e.g., processing pipelines) are currently using the project directory or its database.
- **Impact:** On Windows, `rmtree` will fail if the database file is open (`PermissionError`). On other systems, it might delete files while a thread is writing, leading to crashes or "zombie" processes.

### 2.2 Incomplete Exception Handling in Pipeline
- **File:** `backend/services/pipeline.py`
- **Line:** 164
- **Description:** A broad `except Exception as e` catches all errors during frame processing. While it logs the error and increments `error_count`, it doesn't distinguish between recoverable errors (e.g., a single corrupt frame) and fatal ones (e.g., GPU memory exhaustion or database disk full).
- **Impact:** The pipeline might continue "running" in a broken state for thousands of frames, filling logs and not producing results.

### 2.3 `cv2` and `numpy` No-Member Errors (Pylint False Positives)
- **Files:** Most backend files using OpenCV or NumPy.
- **Description:** Pylint reports `E1101: Module 'cv2' has no '...' member`. This is a known issue with Pylint and C-extensions.
- **Status:** Investigated and confirmed as false positives, but they clutter CI/CD reports and might hide real `AttributeError` issues if not properly suppressed via configuration.

## 3. Findings from Test Suite

### 3.1 Deprecation Warnings
- **Description:** 38 warnings during `pytest` execution.
- **Key Warnings:**
    - `DeprecationWarning: distutils Version classes are deprecated` (from `thop`).
    - `DeprecationWarning: datetime.datetime.utcnow() is deprecated` (from `openpyxl`).
    - `DeprecationWarning: The 'app' shortcut is now deprecated` (from `httpx`).
- **Impact:** Future Python or library updates will break these components.

---
*Generated on 2026-03-25*
