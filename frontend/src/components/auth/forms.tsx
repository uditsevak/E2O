"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircleIcon, Loader2Icon } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/client";
import { useLogin, useSignup } from "@/lib/queries";

import { AuthLayout } from "./auth-layout";
import { GoogleButton } from "./google-button";
import { useFieldId } from "@/lib/use-field-id";

function useNext(): string {
  const next = useSearchParams().get("next");
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <Alert variant="destructive">
      <AlertCircleIcon />
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}

export function LoginForm() {
  const fid = useFieldId();
  const router = useRouter();
  const next = useNext();
  const queryError = useSearchParams().get("error");
  const login = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  return (
    <AuthLayout
      title="Sign in"
      subtitle="See every enquiry from every inbox."
      footer={
        <>
          New here?{" "}
          <Link
            className="text-primary font-medium"
            href={`/signup?next=${encodeURIComponent(next)}`}
          >
            Create an account
          </Link>
        </>
      }
    >
      <GoogleButton next={next} />
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          login.mutate({ email, password }, { onSuccess: () => router.replace(next) });
        }}
      >
        <FormError message={login.error ? errorMessage(login.error) : queryError} />
        <div className="space-y-2">
          <Label htmlFor={fid("email")}>Email</Label>
          <Input
            id={fid("email")}
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={fid("password")}>Password</Label>
          <Input
            id={fid("password")}
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <Button type="submit" className="w-full" disabled={login.isPending}>
          {login.isPending && <Loader2Icon className="animate-spin" />} Sign in
        </Button>
      </form>
    </AuthLayout>
  );
}

export function SignupForm() {
  const fid = useFieldId();
  const router = useRouter();
  const next = useNext();
  const signup = useSignup();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Free during the pilot. Takes a minute."
      footer={
        <>
          Already have an account?{" "}
          <Link
            className="text-primary font-medium"
            href={`/login?next=${encodeURIComponent(next)}`}
          >
            Sign in
          </Link>
        </>
      }
    >
      <GoogleButton next={next} />
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          signup.mutate(
            { name, email, password },
            { onSuccess: () => router.replace(next === "/" ? "/onboarding" : next) },
          );
        }}
      >
        <FormError message={signup.error ? errorMessage(signup.error) : null} />
        <div className="space-y-2">
          <Label htmlFor={fid("name")}>Your name</Label>
          <Input
            id={fid("name")}
            autoComplete="name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={fid("email")}>Work email</Label>
          <Input
            id={fid("email")}
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={fid("password")}>Password</Label>
          <Input
            id={fid("password")}
            type="password"
            autoComplete="new-password"
            minLength={8}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <p className="text-muted-foreground text-xs">At least 8 characters.</p>
        </div>
        <Button type="submit" className="w-full" disabled={signup.isPending}>
          {signup.isPending && <Loader2Icon className="animate-spin" />} Create account
        </Button>
      </form>
    </AuthLayout>
  );
}
