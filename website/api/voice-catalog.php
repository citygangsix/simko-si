<?php
declare(strict_types=1);

/**
 * 28 sea-creature names. The uploaded voice script loads them from
 * /api/voice/voices (they are not hardcoded there). Each name maps to one
 * built-in xAI TTS voice.
 *
 * @return list<array{id:string,name:string,tone:string,xai:string}>
 */
function simko_voice_catalog(): array
{
    return [
        ['id' => 'coral', 'name' => 'Coral', 'tone' => 'Soft and soothing', 'xai' => 'carina'],
        ['id' => 'kelp', 'name' => 'Kelp', 'tone' => 'Gentle and patient', 'xai' => 'luna'],
        ['id' => 'manta', 'name' => 'Manta', 'tone' => 'Rich and cinematic', 'xai' => 'orion'],
        ['id' => 'nautilus', 'name' => 'Nautilus', 'tone' => 'Elegant and refined', 'xai' => 'altair'],
        ['id' => 'dolphin', 'name' => 'Dolphin', 'tone' => 'Friendly and upbeat', 'xai' => 'iris'],
        ['id' => 'orca', 'name' => 'Orca', 'tone' => 'Powerful and dramatic', 'xai' => 'zagan'],
        ['id' => 'turtle', 'name' => 'Turtle', 'tone' => 'Calm and wise', 'xai' => 'lux'],
        ['id' => 'seahorse', 'name' => 'Seahorse', 'tone' => 'Playful and quick', 'xai' => 'sirius'],
        ['id' => 'starfish', 'name' => 'Starfish', 'tone' => 'Bright and energetic', 'xai' => 'helios'],
        ['id' => 'anemone', 'name' => 'Anemone', 'tone' => 'Reassuring and warm', 'xai' => 'celeste'],
        ['id' => 'urchin', 'name' => 'Urchin', 'tone' => 'Sharp and focused', 'xai' => 'zenith'],
        ['id' => 'octopus', 'name' => 'Octopus', 'tone' => 'Inventive and curious', 'xai' => 'kepler'],
        ['id' => 'squid', 'name' => 'Squid', 'tone' => 'Precise and steady', 'xai' => 'rigel'],
        ['id' => 'jellyfish', 'name' => 'Jellyfish', 'tone' => 'Serene and radiant', 'xai' => 'aurora'],
        ['id' => 'manatee', 'name' => 'Manatee', 'tone' => 'Warm and steadfast', 'xai' => 'ursa'],
        ['id' => 'walrus', 'name' => 'Walrus', 'tone' => 'Strong and low', 'xai' => 'leo'],
        ['id' => 'seal', 'name' => 'Seal', 'tone' => 'Smooth and balanced', 'xai' => 'sal'],
        ['id' => 'otter', 'name' => 'Otter', 'tone' => 'Easygoing and kind', 'xai' => 'castor'],
        ['id' => 'marlin', 'name' => 'Marlin', 'tone' => 'Bold and dynamic', 'xai' => 'helix'],
        ['id' => 'ray', 'name' => 'Ray', 'tone' => 'Warm and articulate', 'xai' => 'lumen'],
        ['id' => 'crab', 'name' => 'Crab', 'tone' => 'Clear and confident', 'xai' => 'rex'],
        ['id' => 'lobster', 'name' => 'Lobster', 'tone' => 'Confident and trustworthy', 'xai' => 'perseus'],
        ['id' => 'shrimp', 'name' => 'Shrimp', 'tone' => 'Bright and curious', 'xai' => 'cosmo'],
        ['id' => 'clownfish', 'name' => 'Clownfish', 'tone' => 'Energetic and upbeat', 'xai' => 'eve'],
        ['id' => 'angelfish', 'name' => 'Angelfish', 'tone' => 'Warm and friendly', 'xai' => 'ara'],
        ['id' => 'puffer', 'name' => 'Puffer', 'tone' => 'Thoughtful and wise', 'xai' => 'naksh'],
        ['id' => 'eel', 'name' => 'Eel', 'tone' => 'Commanding and calm', 'xai' => 'atlas'],
        ['id' => 'whale', 'name' => 'Whale', 'tone' => 'Grounded and luminous', 'xai' => 'liora'],
    ];
}

function simko_voice_by_id(string $id): ?array
{
    foreach (simko_voice_catalog() as $voice) {
        if ($voice['id'] === $id) {
            return $voice;
        }
    }
    return null;
}

