const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const fs = require("fs");

const TEAL = "2EC4B6", AMBER = "FFB454", CORAL = "FF6B81", WHITE = "FFFFFF", MUTED = "8AA0B4";

const icons = {
  book:   [fa.FaBookOpen, WHITE],
  layer:  [fa.FaLayerGroup, WHITE],
  file:   [fa.FaRegFileAlt, TEAL],
  brain:  [fa.FaBrain, WHITE],
  hash:   [fa.FaHashtag, WHITE],
  branch: [fa.FaCodeBranch, WHITE],
  filter: [fa.FaFilter, WHITE],
  search: [fa.FaSearch, WHITE],
  check:  [fa.FaCheckCircle, TEAL],
  quote:  [fa.FaQuoteRight, MUTED],
  bolt:   [fa.FaBolt, AMBER],
  db:     [fa.FaDatabase, WHITE],
};

(async () => {
  fs.mkdirSync("icons", { recursive: true });
  for (const [name, [Comp, color]] of Object.entries(icons)) {
    const svg = renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size: 256 }));
    await sharp(Buffer.from(svg), { density: 300 }).resize(256, 256, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } }).png().toFile(`icons/${name}.png`);
    console.log("ok", name);
  }
})();
