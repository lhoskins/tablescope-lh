# RemindMe

AI-powered personal memory assistant for networking events and life moments.

## Overview

RemindMe helps you remember people, conversations, and important moments by letting you quickly capture thoughts via voice, text, or screenshots—then AI organizes everything for you.

### Key Features

- **Quick Capture**: Record voice notes, type, or paste from your Notes app
- **AI Organization**: Automatically structures memories into people, events, and follow-ups
- **Section Filters**: Organize by Personal, Business, Projects, Relationships, ToDos, Events, Trips
- **Smart Insights**: AI evaluates inspiration level and relationship potential
- **Follow-up Tracking**: Never forget to reconnect with important contacts

## Getting Started

### Prerequisites

- Node.js 18+ and npm

### Installation

```bash
# Clone the repo
git clone https://github.com/etlagent/remindme.git
cd remindme

# Install dependencies
npm install

# Run development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) to see the app.

### Running Offline (for travel)

The app works fully offline for UI development. Database and AI features will be added in future updates.

## Current Status

**Phase 1: UI Prototype** ✅
- Split-screen layout (Capture + Library)
- Section filtering system
- Mock data for People, Events, and Follow-ups
- Mobile-responsive design matching Etlagent style

**Phase 2: Database Integration** (Next)
- Supabase connection
- Real data persistence
- User authentication

**Phase 3: AI Features** (Upcoming)
- OpenAI Whisper for voice transcription
- GPT-4 for memory structuring
- Q&A chat interface

## Tech Stack

- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **Components**: Shadcn/ui
- **Icons**: Lucide React
- **Database**: Supabase (planned)
- **AI**: OpenAI (planned)

## Project Structure

```
remindme/
├── app/
│   ├── page.tsx          # Main split-screen UI
│   ├── layout.tsx        # Root layout
│   └── globals.css       # Global styles
├── components/
│   └── ui/               # Shadcn components
└── lib/
    └── utils.ts          # Utility functions
```

## Roadmap

- [ ] Connect to Supabase database
- [ ] Implement voice recording and transcription
- [ ] Add OpenAI memory structuring
- [ ] Build Q&A chat interface
- [ ] Create person and event detail pages
- [ ] Add screenshot OCR processing
- [ ] Deploy to remindme.vitruvity.com
- [ ] Mobile app integration with Bookmark/Agora

## License

Private project for Etlagent/Vitruvity.
