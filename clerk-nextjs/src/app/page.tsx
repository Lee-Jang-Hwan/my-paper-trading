import { SignInButton, SignUpButton } from "@clerk/nextjs";
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

export default async function LandingPage() {
  const { userId } = await auth();

  if (userId) {
    redirect("/dashboard");
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4">
      <main className="flex max-w-2xl flex-col items-center gap-8 text-center">
        {/* Logo / Title */}
        <div className="flex flex-col items-center gap-4">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary text-2xl font-bold text-primary-foreground">
            OP
          </div>
          <h1 className="text-4xl font-bold tracking-tight text-foreground sm:text-5xl">
            OUR Paper Trading
          </h1>
        </div>

        {/* Subtitle */}
        <p className="max-w-md text-lg text-muted-foreground">
          AI 에이전트와 함께하는 모의 주식 투자
        </p>

        {/* Description */}
        <p className="max-w-lg text-sm text-muted-foreground">
          실시간 시장 데이터와 AI 분석을 기반으로 가상 자금으로 주식 투자를
          연습하세요. 리스크 없이 투자 전략을 테스트할 수 있습니다.
        </p>

        {/* CTA Buttons */}
        <div className="flex flex-col gap-3 sm:flex-row">
          <SignInButton mode="modal">
            <button className="inline-flex h-12 items-center justify-center rounded-lg bg-primary px-8 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90">
              로그인
            </button>
          </SignInButton>
          <SignUpButton mode="modal">
            <button className="inline-flex h-12 items-center justify-center rounded-lg border border-border bg-background px-8 text-sm font-medium text-foreground transition-colors hover:bg-muted">
              시작하기
            </button>
          </SignUpButton>
        </div>

        {/* Features Preview */}
        <div className="mt-8 grid w-full max-w-lg grid-cols-3 gap-4 text-center">
          <div className="rounded-lg border border-border bg-card p-4">
            <p className="text-2xl font-bold text-primary">실시간</p>
            <p className="mt-1 text-xs text-muted-foreground">시장 데이터</p>
          </div>
          <div className="rounded-lg border border-border bg-card p-4">
            <p className="text-2xl font-bold text-accent">AI</p>
            <p className="mt-1 text-xs text-muted-foreground">투자 에이전트</p>
          </div>
          <div className="rounded-lg border border-border bg-card p-4">
            <p className="text-2xl font-bold text-foreground">무료</p>
            <p className="mt-1 text-xs text-muted-foreground">모의 투자</p>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="mt-16 pb-8 text-xs text-muted-foreground">
        OUR Paper Trading &copy; {new Date().getFullYear()}
      </footer>
    </div>
  );
}
