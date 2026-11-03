#!/usr/bin/env node
/*
 * Runs create_semantic_validation_form.gs against a recording mock of Google's FormApp/Utilities/Logger and prints,
 * as JSON, every item the script would create (type, title, help text, choices, required) plus the form settings.
 * Used by `semantic_validation.py form` and the tests to check exactly what a reviewer would see -- without a Google
 * account. Usage: node scripts/evaluation/simulate_form.js <script.gs>
 */
const fs = require('fs');
const vm = require('vm');
const crypto = require('crypto');

const src = fs.readFileSync(process.argv[2], 'utf8');
const record = {settings: {}, items: [], logs: []};

function item(type) {
  const it = {type, title: '', help: '', choices: null, required: false};
  record.items.push(it);
  const api = {
    setTitle(t) { it.title = t; return api; },
    setHelpText(t) { it.help = t; return api; },
    setChoiceValues(v) { it.choices = v.slice(); return api; },
    setRequired(r) { it.required = r; return api; },
    getType() { return type; },
  };
  return api;
}

const ItemType = {PAGE_BREAK: 'PAGE_BREAK', MULTIPLE_CHOICE: 'MULTIPLE_CHOICE', PARAGRAPH_TEXT: 'PARAGRAPH_TEXT',
  TEXT: 'TEXT'};
const form = {
  setDescription(d) { record.settings.description = d; },
  setEmailCollectionType(t) { record.settings.emailCollection = t; },
  setCollectEmail(v) { record.settings.collectEmail = v; },
  setRequireLogin(v) { record.settings.requireLogin = v; },
  setLimitOneResponsePerUser(v) { record.settings.limitOneResponsePerUser = v; },
  setAllowResponseEdits(v) { record.settings.allowResponseEdits = v; },
  setPublishingSummary(v) { record.settings.publishingSummary = v; },
  setShowLinkToRespondAgain(v) { record.settings.showLinkToRespondAgain = v; },
  setShuffleQuestions(v) { record.settings.shuffleQuestions = v; },
  setProgressBar(v) { record.settings.progressBar = v; },
  setConfirmationMessage(m) { record.settings.confirmation = m; },
  setAcceptingResponses(v) { record.settings.acceptingResponses = v; },
  setPublished(v) { record.settings.published = v; },
  isPublished() { return record.settings.published === true; },
  addTextItem() { return item(ItemType.TEXT); },
  addPageBreakItem() { return item(ItemType.PAGE_BREAK); },
  addMultipleChoiceItem() { return item(ItemType.MULTIPLE_CHOICE); },
  addParagraphTextItem() { return item(ItemType.PARAGRAPH_TEXT); },
  getItems() { return record.items.map(i => ({getType: () => i.type})); },
  getPublishedUrl() { return 'https://docs.google.com/forms/d/e/SIMULATED/viewform'; },
  shortenFormUrl(u) { return u; },
  getEditUrl() { return 'https://docs.google.com/forms/d/SIMULATED/edit'; },
  getId() { return 'SIMULATED'; },
};
const sandbox = {
  FormApp: {
    create(title) { record.settings.title = title; return form; },
    ItemType, EmailCollectionType: {DO_NOT_COLLECT: 'DO_NOT_COLLECT'},
  },
  Utilities: {
    DigestAlgorithm: {SHA_256: 'sha256'}, Charset: {UTF_8: 'utf8'},
    computeDigest(alg, value) {
      return Array.from(crypto.createHash('sha256').update(value, 'utf8').digest()).map(b => (b > 127 ? b - 256 : b));
    },
  },
  Logger: {log(m) { record.logs.push(String(m)); }},
  JSON,
};
vm.createContext(sandbox);
vm.runInContext(src, sandbox);
record.result = vm.runInContext('createSemanticValidationForm()', sandbox);
process.stdout.write(JSON.stringify(record));
