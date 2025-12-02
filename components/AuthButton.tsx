"use client";

import { useState, useEffect } from "react";
import { supabase } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { LogIn, LogOut, User } from "lucide-react";
import type { User as SupabaseUser } from "@supabase/supabase-js";

export function AuthButton() {
  const [user, setUser] = useState<SupabaseUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [showEmailInput, setShowEmailInput] = useState(false);
  const [email, setEmail] = useState("");
  const [emailSent, setEmailSent] = useState(false);

  useEffect(() => {
    // Check current session
    supabase.auth.getSession().then(({ data: { session } }) => {
      setUser(session?.user ?? null);
      setLoading(false);
    });

    // Listen for auth changes
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
    });

    return () => subscription.unsubscribe();
  }, []);

  const handleSignIn = async () => {
    if (!email) return;

    setLoading(true);
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: window.location.origin,
      },
    });

    if (error) {
      alert(`Error: ${error.message}`);
    } else {
      setEmailSent(true);
    }
    setLoading(false);
  };

  const handleSignOut = async () => {
    setLoading(true);
    await supabase.auth.signOut();
    setUser(null);
    setLoading(false);
  };

  if (loading) {
    return (
      <Button variant="ghost" size="sm" disabled>
        <User className="h-4 w-4 mr-2" />
        Loading...
      </Button>
    );
  }

  if (user) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-sm text-gray-600 hidden sm:inline">
          {user.email}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleSignOut}
          className="text-gray-700 hover:text-gray-900"
        >
          <LogOut className="h-4 w-4 mr-2" />
          Sign Out
        </Button>
      </div>
    );
  }

  if (showEmailInput) {
    return (
      <div className="flex items-center gap-2">
        {emailSent ? (
          <div className="text-sm text-green-600">
            Check your email for the magic link!
          </div>
        ) : (
          <>
            <input
              type="email"
              placeholder="your@email.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSignIn()}
              className="px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              autoFocus
            />
            <Button
              size="sm"
              onClick={handleSignIn}
              disabled={!email || loading}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              Send Link
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowEmailInput(false)}
            >
              Cancel
            </Button>
          </>
        )}
      </div>
    );
  }

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => setShowEmailInput(true)}
      className="text-gray-700 hover:text-gray-900"
    >
      <LogIn className="h-4 w-4 mr-2" />
      Sign In
    </Button>
  );
}
