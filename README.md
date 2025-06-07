# Recipe Populator Figma Plugin

A Figma plugin that populates selected frames with recipe data from a local CSV file.

## Features

- Load recipe data from a local CSV file
- Search recipes using a simple text input
- Automatically populate selected frames with matching recipe data
- Support for text and image fields
- Detailed logging for debugging

## CSV Format

The plugin expects a CSV file with the following columns:

- Recipe Image (URL)
- Recipe Title
- Time
- Chef Image (URL)
- Chef Name
- Dietary
- Description

## Usage

1. Select one or more frames in your Figma document
2. Launch the plugin
3. Upload your CSV file using the "Upload CSV" button
4. Enter a search query in the search box
5. Click "Search" to populate the selected frames with matching recipes

## Frame Setup

For the plugin to work correctly, your frames should have layers named exactly as the CSV columns:

- Recipe Image
- Recipe Title
- Time
- Chef Image
- Chef Name
- Dietary
- Description

The plugin will:
- Update text layers with the corresponding text content
- Set image fills for layers named "Recipe Image" and "Chef Image" using the provided URLs

## Development

This plugin is built with:
- TypeScript
- Figma Plugin API

To build the plugin:

1. Install dependencies:
```bash
npm install
```

2. Build the plugin:
```bash
npm run build
```

3. Watch for changes:
```bash
npm run watch
```

## License

MIT

Below are the steps to get your plugin running. You can also find instructions at:

  https://www.figma.com/plugin-docs/plugin-quickstart-guide/

This plugin template uses Typescript and NPM, two standard tools in creating JavaScript applications.

First, download Node.js which comes with NPM. This will allow you to install TypeScript and other
libraries. You can find the download link here:

  https://nodejs.org/en/download/

Next, install TypeScript using the command:

  npm install -g typescript

Finally, in the directory of your plugin, get the latest type definitions for the plugin API by running:

  npm install --save-dev @figma/plugin-typings

If you are familiar with JavaScript, TypeScript will look very familiar. In fact, valid JavaScript code
is already valid Typescript code.

TypeScript adds type annotations to variables. This allows code editors such as Visual Studio Code
to provide information about the Figma API while you are writing code, as well as help catch bugs
you previously didn't notice.

For more information, visit https://www.typescriptlang.org/

Using TypeScript requires a compiler to convert TypeScript (code.ts) into JavaScript (code.js)
for the browser to run.

We recommend writing TypeScript code using Visual Studio code:

1. Download Visual Studio Code if you haven't already: https://code.visualstudio.com/.
2. Open this directory in Visual Studio Code.
3. Compile TypeScript to JavaScript: Run the "Terminal > Run Build Task..." menu item,
    then select "npm: watch". You will have to do this again every time
    you reopen Visual Studio Code.

That's it! Visual Studio Code will regenerate the JavaScript file every time you save.
>>>>>>> 937b693 (Initial commit: Figma Recipe Populator Plugin files)
