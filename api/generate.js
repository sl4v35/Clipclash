// api/generate.js
import { GoogleGenerativeAI } from '@google/generative-ai';

export const config = {
  maxDuration: 60,
};

export default async function handler(req, res) {
  // CORS Setup
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST,OPTIONS');
  res.setHeader(
    'Access-Control-Allow-Headers',
    'X-CSRF-Token, X-Requested-With, Accept, Accept-Version, Content-Length, Content-MD5, Content-Type, Date, X-Api-Version'
  );

  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method Not Allowed' });
  }

  const { videoUrl, quantity } = req.body;

  if (!videoUrl) {
    return res.status(400).json({ error: 'Video URL is required' });
  }

  const targetCount = quantity === 50 ? 50 : 20;

  try {
    const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
    const model = genAI.getGenerativeModel({ 
        model: 'gemini-1.5-flash',
        generationConfig: { responseMimeType: "application/json" }
    });

    const prompt = `
      Analyze this video URL context: ${videoUrl}
      Generate exactly ${targetCount} viral short video ideas.
      Each idea must include:
      - "hook": Short punchy first sentence.
      - "body": Main script (2-3 sentences).
      - "tags": 12 hashtags.
      
      Output JSON structure:
      {
        "clips": [
          { "id": 1, "hook": "...", "body": "...", "tags": "..." }
        ]
      }
    `;

    const result = await model.generateContent(prompt);
    const response = await result.response;
    const text = response.text();
    const data = JSON.parse(text);

    return res.status(200).json(data);

  } catch (error) {
    console.error('Error:', error);
    return res.status(500).json({ error: 'Generation failed', details: error.message });
  }
}
