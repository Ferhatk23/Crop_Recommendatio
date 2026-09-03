/**
 * Meldet den Auflöser an. Wird über `node --import` geladen, damit er auch
 * in den Kindprozessen greift, die der Test-Runner je Testdatei startet.
 */

import { register } from 'node:module';

register('./ts-resolve.mjs', import.meta.url);
