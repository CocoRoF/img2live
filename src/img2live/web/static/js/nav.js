// SPDX-License-Identifier: Apache-2.0
// Header: the number of puppets in this browser's list next to "내 퍼펫".
import { mine } from "./mine.js";
const c = document.getElementById("navMineCount");
if (c) { const n = mine.list().length; c.textContent = n ? String(n) : ""; }
