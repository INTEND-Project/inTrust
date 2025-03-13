const createPlugin = require("@extism/extism")

var testFunction = async function(text) {
    const plugin = await createPlugin(
        'https://github.com/extism/plugins/releases/latest/download/count_vowels.wasm',
        { useWasi: true }
    );
    let out = await plugin.call("count_vowels", text);
    //console.log(out.text())
    return out.text()
}

exports.testFunction = testFunction;

