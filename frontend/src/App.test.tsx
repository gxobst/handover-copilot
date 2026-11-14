import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from './App'

describe('App Smoke Test', () => {
  it('renders the application title/heading successfully', () => {
    render(<App />)

    const heading = screen.getByRole('heading', {
      level: 1,
      name: /shift handover copilot/i,
    })
    expect(heading).toBeInTheDocument()

    const titleText = screen.getByText('Shift Handover Copilot')
    expect(titleText).toBeInTheDocument()
  })

  it('renders design system category badges', () => {
    render(<App />)

    expect(screen.getByText('downtime')).toBeInTheDocument()
    expect(screen.getByText('quality')).toBeInTheDocument()
    expect(screen.getByText('safety')).toBeInTheDocument()
    expect(screen.getByText('info')).toBeInTheDocument()
  })
})
