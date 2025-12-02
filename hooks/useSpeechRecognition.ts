import { useEffect, useRef, useState } from "react";

// Extend Window interface for browser speech recognition
declare global {
  interface Window {
    SpeechRecognition: any;
    webkitSpeechRecognition: any;
  }
}

export function useSpeechRecognition() {
  const [isListening, setIsListening] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const recognitionRef = useRef<any>(null);

  useEffect(() => {
    if (typeof window !== "undefined" && !recognitionRef.current) {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      
      if (SpeechRecognition) {
        const recognition = new SpeechRecognition();
        recognition.continuous = false; // Stop after each phrase (snippet mode)
        recognition.interimResults = false;
        recognition.lang = "en-US";

        recognitionRef.current = recognition;
      }
    }

    return () => {
      if (recognitionRef.current) {
        try {
          recognitionRef.current.abort();
        } catch (e) {
          // Ignore errors on cleanup
        }
      }
    };
  }, []);

  const startListening = (onResult: (transcript: string) => void) => {
    if (!recognitionRef.current) {
      alert("Speech recognition is not supported in this browser. Please use Chrome, Safari, or Edge.");
      return;
    }

    recognitionRef.current.onresult = (event: any) => {
      const transcript = event.results[event.results.length - 1][0].transcript;
      onResult(transcript);
    };

    recognitionRef.current.onerror = (event: any) => {
      console.error("Speech recognition error:", event.error);
      setIsListening(false);
      setIsRecording(false);
    };

    recognitionRef.current.onend = () => {
      setIsListening(false);
      setIsRecording(false);
    };

    try {
      recognitionRef.current.start();
      setIsListening(true);
      setIsRecording(true);
    } catch (error) {
      console.error("Error starting speech recognition:", error);
    }
  };

  const stopListening = () => {
    if (recognitionRef.current && isListening) {
      recognitionRef.current.stop();
      setIsListening(false);
      setIsRecording(false);
    }
  };

  const toggleListening = (onResult: (transcript: string) => void) => {
    if (isListening) {
      stopListening();
    } else {
      startListening(onResult);
    }
  };

  return {
    isListening,
    isRecording,
    startListening,
    stopListening,
    toggleListening,
  };
}
