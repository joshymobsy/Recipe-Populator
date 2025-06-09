/// <reference types="@figma/plugin-typings" />

// This plugin will open a window to prompt the user to enter a number, and
// it will then create that many rectangles on the screen.

// This file holds the main code for plugins. Code in this file has access to
// the *figma document* via the figma global object.
// You can access browser APIs in the <script> tag inside "ui.html" which has a
// full browser environment (See https://www.figma.com/plugin-docs/how-plugins-run).

// This shows the HTML page in "ui.html".
figma.showUI(__html__, { width: 400, height: 500 });

interface Recipe {
  'Image': string;
  'Title': string;
  'Time': string;
  'Chef Image': string;
  'Chef Name': string;
  'Description': string;
  'Dietary Requirements': string;
  [key: string]: string;
}

interface PluginMessage {
  type: string;
  query?: string;
  csvData?: string;
}

function log(message: string) {
  figma.ui.postMessage({ type: 'log', message });
}

function showError(message: string) {
  figma.ui.postMessage({ type: 'error', message });
}

function parseCSV(csvData: string): Recipe[] {
  const lines = csvData.split(/\r?\n/).filter(line => line.trim() !== ''); 
  if (lines.length === 0) {
    log('Error: CSV data is empty or contains no valid lines.');
    return [];
  }
  
  const recipes: Recipe[] = [];
  let headers: string[] = [];
  const MAX_FIELDS_PER_ROW = 1000; 

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const values: string[] = [];
    let inQuote = false;
    let currentField = '';
    
    for (let j = 0; j < line.length; j++) {
      const char = line[j];
      const nextChar = line[j + 1];

      if (char === '"') {
        if (inQuote && nextChar === '"') { 
          currentField += '"';
          j++; 
        } else {
          inQuote = !inQuote;
        }
      } else if (char === ',') {
        if (inQuote) {
          currentField += char;
        } else {
          values.push(currentField.trim());
          currentField = '';
          if (values.length > MAX_FIELDS_PER_ROW) {
            log(`Warning: Exceeded MAX_FIELDS_PER_ROW (${MAX_FIELDS_PER_ROW}) while parsing line ${i}. Aborting parsing for this line.`);
            break; 
          }
        }
      } else {
        currentField += char;
      }
    }
    values.push(currentField.trim()); 
    if (values.length > MAX_FIELDS_PER_ROW) {
      log(`Warning: Final field count exceeded MAX_FIELDS_PER_ROW (${MAX_FIELDS_PER_ROW}) for line ${i}.`);
    }

    if (i === 0) {
      headers = values;
      log(`Detected CSV Headers: [${headers.map(h => `"${h}"`).join(', ')}]`);
      if (headers.length === 0) {
        log('Warning: No headers detected in the CSV file.');
      }
    } else {
      const recipe: Partial<Recipe> = {};
      headers.forEach((header, index) => {
        const value = values[index] !== undefined ? values[index] : '';
        recipe[header as keyof Recipe] = value;
      });
      recipes.push(recipe as Recipe);
    }
  }
  return recipes;
}

function findMatchingRecipes(recipes: Recipe[], query: string): Recipe[] {
  const searchQuery = query.toLowerCase();
  return recipes
    .filter(recipe => {
      return Object.values(recipe).some(value => 
        value.toLowerCase().includes(searchQuery)
      );
    })
    .sort((a, b) => {
      const aMatches = Object.values(a).filter(value => 
        value.toLowerCase().includes(searchQuery)
      ).length;
      const bMatches = Object.values(b).filter(value => 
        value.toLowerCase().includes(searchQuery)
      ).length;
      return bMatches - aMatches;
    });
}

// Helper to decode Base64 to ArrayBuffer
function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binaryString = atob(base64);
  const len = binaryString.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}

// New function to pick random recipes
function pickRandomRecipes(recipes: Recipe[], count: number): Recipe[] {
  const shuffled = [...recipes].sort(() => 0.5 - Math.random());
  return shuffled.slice(0, count);
}

async function updateLayer(layer: SceneNode, value: string, isImage: boolean) {
  if (isImage) {
    log(`[Image] Attempting to update layer: "${layer.name}" with value (URL or Base64): "${value.substring(0, 50)}..."`);
    try {
      let imageData: ArrayBuffer;

      if (value.startsWith('data:image')) {
        log(`[Image] Detected Base64 image data for layer: "${layer.name}"`);
        const base64Content = value.split(',')[1];
        imageData = base64ToArrayBuffer(base64Content);
      } else {
        log(`[Image] Fetching image from URL: ${value}`);
        const response = await fetch(value);
        
        log(`[Image] Fetch response received. Status: ${response.status}, StatusText: ${response.statusText}, Type: ${response.type}`);
        
        if (!response.ok) {
          throw new Error(`[Image] HTTP error fetching image! Status: ${response.status} (${response.statusText || 'No Status Text'})`);
        }

        imageData = await response.arrayBuffer();
        log(`[Image] Successfully obtained ArrayBuffer from fetch response.`);
      }

      if (imageData.byteLength === 0) {
        log(`[Image] Warning: Image data (ArrayBuffer) is empty for URL/Base64: "${value.substring(0, 50)}...". Image may not load correctly.`);
        throw new Error('[Image] Empty image data.');
      }

      const image = figma.createImage(new Uint8Array(imageData));
      if ('fills' in layer) {
        layer.fills = [{
          type: 'IMAGE',
          scaleMode: 'FILL',
          imageHash: image.hash,
          imageTransform: [[1, 0, 0], [0, 1, 0]]
        }];
        log(`[Image] Successfully set image fill for layer: "${layer.name}" with hash: ${image.hash}`);
      }
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      log(`[Image] Critical Error loading image for layer "${layer.name}" from "${value.substring(0, 50)}...": ${errorMessage}`);
      log(`[Image] Possible reasons: Network issue (ERR_NAME_NOT_RESOLVED/CORS), invalid image data, malformed Base64, or other internal Figma plugin errors.`);
    }
  } else if ('characters' in layer) {
    try {
      const fontName = { family: "General Sans Variable", style: "Medium" };
      await figma.loadFontAsync(fontName);
      layer.characters = value;
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      log(`[Text] Error updating text for layer "${layer.name}": ${errorMessage}`);
    }
  }
}

// New recursive helper function to find layers by name
function findLayersByName(node: SceneNode | ChildrenMixin, name: string): SceneNode[] {
  const foundLayers: SceneNode[] = [];
  if ('children' in node) {
    for (const child of node.children) {
      if (child.name === name) {
        foundLayers.push(child);
      }
      // Recursively search in children that can have children
      if ('children' in child) {
        foundLayers.push(...findLayersByName(child, name));
      }
    }
  }
  return foundLayers;
}

async function populateFrame(frame: SceneNode, recipe: Recipe) {
  log(`[Frame] Populating frame/instance: "${frame.name}" with recipe: "${recipe.Title || '(No Title)'}"`);
  
  const fieldsToPopulate = [
    { csvField: 'Image', layerName: 'Image', isImage: true }, 
    { csvField: 'Title', layerName: 'Title', isImage: false },
    { csvField: 'Time', layerName: 'Time', isImage: false }, 
    { csvField: 'Chef Image', layerName: 'Chef Image', isImage: true },
    { csvField: 'Chef Name', layerName: 'Chef Name', isImage: false },
    { csvField: 'Description', layerName: 'Description', isImage: false },
    { csvField: 'Dietary Requirements', layerName: 'Dietary Requirements', isImage: false },
  ];

  for (const field of fieldsToPopulate) {
    const layers = findLayersByName(frame, field.layerName);
    if (layers.length > 0) {
      const value = recipe[field.csvField];
      if (value) {
        for (const layer of layers) {
          await updateLayer(layer, value, field.isImage);
    }
      }
    }
  }
}

figma.ui.onmessage = async (msg: PluginMessage) => {
  if (msg.type === 'search-recipes' && msg.query && msg.csvData) {
    try {
      log(`----- Plugin Execution Start: ${new Date().toISOString()} -----`);
      log(`User search query: "${msg.query}"`);
      log(`Attempting to parse CSV data provided by user...`);
      const recipes = parseCSV(msg.csvData);
      log(`Successfully parsed ${recipes.length} recipes from CSV data.`);
      
      let recipesToPopulate: Recipe[] = [];

      if (msg.query) {
        log(`Searching for recipes matching query "${msg.query}"...`);
        recipesToPopulate = findMatchingRecipes(recipes, msg.query);
      } else {
        const selectionCount = figma.currentPage.selection.filter(node => node.type === 'FRAME' || node.type === 'INSTANCE').length;
        const numRecipesToPick = Math.max(1, selectionCount > 0 ? selectionCount : 5); // Pick at least 1, or 5 if no frames/instances selected
        log(`No search query provided. Picking ${numRecipesToPick} random recipes.`);
        recipesToPopulate = pickRandomRecipes(recipes, numRecipesToPick);
      }

      if (recipesToPopulate.length === 0) {
        showError('No matching recipes found, or no recipes available to pick randomly. Please refine your search or upload a valid CSV.');
        log(`----- Plugin Execution End (No Matches/Random Pick) -----`);
        return;
      }
      
      const selection = figma.currentPage.selection;
      if (selection.length === 0) {
        showError('Please select at least one frame or instance to populate.');
        log(`----- Plugin Execution End (No Selection) -----`);
        return;
      }
      
      log(`Found ${recipesToPopulate.length} recipes to populate (matches or random picks).`);
      log(`User has ${selection.length} Figma frames/instances selected for population.`);
      
      for (let i = 0; i < selection.length; i++) {
        const node = selection[i];
        if (node.type === 'FRAME' || node.type === 'INSTANCE') {
          const recipe = recipesToPopulate[i % recipesToPopulate.length];
          log(`Populating selected frame/instance ${i + 1}/${selection.length}: "${node.name}" with recipe title: "${recipe.Title || '(No Title)'}"`);
          await populateFrame(node, recipe);
        } else {
          log(`Warning: Skipping selected node "${node.name}" (type: ${node.type}) as it is not a Frame or Instance. Only frames and instances can be populated.`);
        }
      }
      
      const populatedCount = selection.filter(node => node.type === 'FRAME' || node.type === 'INSTANCE').length;
      log(`Successfully populated ${populatedCount} recipe cards!`);
      log('Recipe population process complete!');
      log(`----- Plugin Execution End (Success) -----`);
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      showError(`Error: ${errorMessage}`);
      log(`Error during plugin execution: ${errorMessage}`);
      log(`----- Plugin Execution End (with Error) -----`);
    }
  }
};