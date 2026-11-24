#!/usr/bin/env node
// Compose the unmodified upstream validator with this repository's root.
const path = require('node:path');
require('./vendor/copilot_sdd/infrastructure/specification_catalog_validator.cjs')
  .main(process.argv.slice(2), path.resolve(__dirname, '..'));
