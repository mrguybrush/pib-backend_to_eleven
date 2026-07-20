import * as Blockly from 'blockly';
import * as http from 'http';
import { pythonGenerator } from './pib-blockly/program-generators/custom-generators';
import { customBlockDefinition } from './pib-blockly/program-blocks/custom-blocks';
import { PIB_BLOCKLY_LOCALES, DEFAULT_LOCALE_CODE } from './pib-blockly/i18n/pib-blockly-locales';

function codeVisualToPython(codeVisual: string): string {
    let workspaceContent;
    try {
        workspaceContent = JSON.parse(codeVisual);
    } catch (error) {
        throw new Error("input is not a well-formed json");
    }
    Blockly.serialization.workspaces.load(workspaceContent, workspace);
    return pythonGenerator.workspaceToCode(workspace);
}

function respond(res: http.ServerResponse<http.IncomingMessage>, code: number, message: string) {
    res.statusCode = code
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.end(message);
}

customBlockDefinition();

// Populate Blockly.Msg with pib's own PIB_* messages, same as the
// frontend's BlocklyLanguageService - without this, %{BKY_PIB_...}
// references in any block with args (e.g. "Warte %1 Sekunden") never
// resolve to text containing "%1"/"%2"/..., so Blockly rejects the block
// the moment a serialized workspace tries to construct it ("Message does
// not reference all N arg(s)"), aborting the WHOLE compile - not just that
// one block. Which locale is applied doesn't matter for this (only the
// %1/%2 placeholders need to resolve, not the surrounding text).
const locale =
    PIB_BLOCKLY_LOCALES.find((l) => l.code === DEFAULT_LOCALE_CODE) ??
    PIB_BLOCKLY_LOCALES[0];
(Blockly as any).setLocale(locale.blocklyPack);
Object.assign(Blockly.Msg, locale.messages);

const workspace = new Blockly.Workspace();
const hostname = '0.0.0.0';
const port = 2442;

const server = http.createServer((req, res) => {
    const buffer: Uint8Array[] = [];
    req.on('data', chunk => buffer.push(chunk));
    req.on('end', () => {
        const codeVisual = Buffer.concat(buffer).toString();
        let codePython: string = "";
        try {
            codePython = codeVisualToPython(codeVisual);
        } catch (error) {
            console.error(`following error occured while compiling input: ${error}.`);
            respond(res, 400, "failed to compile visual-code.")
            return;
        } 
        respond(res, 200, codePython);
    });
});

server.listen(port, hostname, () => {
  console.info(`pib-blockly-server is now listening on http://${hostname}:${port}/ ...`);
}); 